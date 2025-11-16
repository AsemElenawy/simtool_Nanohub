# @package      hubzero-simtool
# @file         run.py
# @copyright    Copyright (c) 2019-2021 The Regents of the University of California.
# @license      http://opensource.org/licenses/MIT MIT
# @trademark    HUBzero is a registered trademark of The Regents of the University of California.
#
import sys
import os
import uuid
import copy
import json
import shutil
import tempfile
import stat
import subprocess
import select
import traceback
from .cache_client import CacheClient, CacheClientException
try:
   from hubzero.submit.SubmitCommand import SubmitCommand
except ImportError:
   submitAvailable = False
else:
   submitAvailable = True

import warnings
import papermill as pm
# location of papermill command line interface corresponding to the imported library
# The PATH environment variable is not set to include the bin directory
# of kernel/Python environment.
# Replace lib/pythonX.Y/site-packages/papermill/__init__.py with bin/papermill
try:
   papermillCLI = os.sep.join(pm.__file__.split(os.sep)[:-5] + ["bin","papermill"])
except:
   papermillCLI = "papermill"

import yaml
from .db import DB
from .experiment import get_experiment
from .datastore import FileDataStore
from .utils import getSimToolInputs, getSimToolOutputs, updateParamsFromDictionary
from .utils import _get_inputs_dict, _get_extra_files, _get_inputFiles, _get_inputs_cache_dict


class RunBase:
   """
   Base class for SimTool Run
   """

   DSHANDLER          = FileDataStore  # local files or NFS.  should be config option
   INPUTFILERUNPREFIX = '.notebookInputFiles'
   SIMTOOLRUNPREFIX   = '.simtool'

   def __init__(self,simToolLocation,inputs,runName,cache,
                     createOutDir=True,remoteAttributes=None,
                     remote=False,trustedExecution=False):
      self.nbName = simToolLocation['simToolName'] + '.ipynb'
      self.inputs = copy.deepcopy(inputs)
      self.input_dict = _get_inputs_dict(self.inputs,inputFileRunPrefix=RunBase.INPUTFILERUNPREFIX)
      self.inputFiles = _get_inputFiles(self.inputs)
      self.outputNames = copy.deepcopy(getSimToolOutputs(simToolLocation).keys())
      inputsSchema = getSimToolInputs(simToolLocation)

# Create landing area for results
      if createOutDir:
         if runName:
            self.runName = runName
         else:
            self.runName = str(uuid.uuid4()).replace('-','')
         self.outdir = os.path.join(get_experiment(),self.runName)
         os.makedirs(self.outdir)
      else:
         self.outdir = os.getcwd()
         self.runName = os.path.basename(self.outdir)

      print("runname = %s" % (self.runName))
      print("outdir  = %s" % (self.outdir))

      self.outname = os.path.join(self.outdir,self.nbName)
      if remote:
         self.remoteSimTool = os.path.join(self.outdir,RunBase.SIMTOOLRUNPREFIX)
         os.makedirs(self.remoteSimTool)
      else:
         self.remoteSimTool = None

      self.cached = False
      self.squidId = ""
      self.dstore = None
      if not trustedExecution:
         if cache:
            hashableInputs = _get_inputs_cache_dict(updateParamsFromDictionary(inputsSchema,self.input_dict))
            self.dstore = RunBase.DSHANDLER(simToolLocation['simToolName'],simToolLocation['simToolRevision'],hashableInputs)
            del hashableInputs
            self.cached = self.dstore.read_cache(self.outdir)

#        print("runname = %s" % (self.runName))
#        print("outdir  = %s" % (self.outdir))
         print("cached  = %s" % (self.cached))

      self.inputsPath = None
      self.db = None
      self.savedOutputFiles = None
      self.savedOutputs = None


   @staticmethod
   def __copySimToolTreeAsLinks(sdir,ddir):
      simToolFiles = os.listdir(sdir)
      for simToolFile in simToolFiles:
         simToolPath = os.path.join(sdir,simToolFile)
         if os.path.isdir(simToolPath):
            shutil.copytree(simToolPath,ddir,copy_function=os.symlink)
         else:
            os.symlink(simToolPath,os.path.join(ddir,simToolFile))


   def setupInputFiles(self,simToolLocation,
                            doSimToolFiles=True,keepSimToolNotebook=False,remote=False,
                            doUserInputFiles=True,
                            doSimToolInputFile=True):
      if doSimToolFiles:
         if remote:
            ddir = self.remoteSimTool
         else:
            ddir = self.outdir
         # Prepare output directory by copying any files that the notebook depends on.
         sdir = os.path.abspath(os.path.dirname(simToolLocation['notebookPath']))
         if simToolLocation['published']:
            # We want to allow simtools to be more than just the notebook,
            # so we recursively copy the notebook directory.
            extraFiles = _get_extra_files(simToolLocation['notebookPath'])
            if   extraFiles == "*":
               self.__copySimToolTreeAsLinks(sdir,ddir)
               # except the notebook itself
               if not keepSimToolNotebook:
                  os.remove(os.path.join(ddir,self.nbName))
            elif extraFiles is not None:
               for extraFile in extraFiles:
                  os.symlink(os.path.abspath(os.path.join(sdir,extraFile)),os.path.join(ddir,extraFile))
               if keepSimToolNotebook:
                  os.symlink(os.path.join(sdir,self.nbName),os.path.join(ddir,self.nbName))
            else:
               if keepSimToolNotebook:
                  os.symlink(os.path.join(sdir,self.nbName),os.path.join(ddir,self.nbName))
         else:
            if keepSimToolNotebook and remote:
               if sdir.startswith('/apps/'):
                  os.symlink(os.path.join(sdir,self.nbName),os.path.join(ddir,self.nbName))
               else:
                  raise ValueError("SimTool notebook must be installed or published to be used remotely")
            extraFiles = _get_extra_files(simToolLocation['notebookPath'])
            # print("EXTRA FILES:",extraFiles)
            if   extraFiles == "*":
               self.__copySimToolTreeAsLinks(sdir,ddir)
               if not keepSimToolNotebook:
                  os.remove(os.path.join(ddir,self.nbName))
            elif extraFiles is not None:
               for extraFile in extraFiles:
                  os.symlink(os.path.abspath(os.path.join(sdir,extraFile)),os.path.join(ddir,extraFile))

      if doUserInputFiles:
         inputFileRunPath = os.path.join(self.outdir,RunBase.INPUTFILERUNPREFIX)
         os.makedirs(inputFileRunPath)
         for inputFile in self.inputFiles:
            shutil.copy2(inputFile,inputFileRunPath)

      if doSimToolInputFile:
# Generate inputs file for cache comparison and/or job input
         self.inputsPath = os.path.join(self.outdir,'inputs.yaml')
         with open(self.inputsPath,'w') as fp:
            yaml.dump(self.input_dict,fp)


   def executeCommand(self,
                      commandArgs,
                      stdin=None,
                      streamOutput=False,
                      reportErrorExit=True):
      exitStatus = 0
      outData = []
      errData = []
      bufferSize = 4096

      if stdin:
         try:
            fpStdin = open(stdin,'rb')
         except:
            exitStatus = 1

      if exitStatus == 0:
         try:
            if stdin:
               child = subprocess.Popen(commandArgs,bufsize=bufferSize,
                                        stdin=fpStdin,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        close_fds=True)
            else:
               child = subprocess.Popen(commandArgs,bufsize=bufferSize,
                                        stdin=None,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        close_fds=True)
         except OSError as e:
            print("Command: %s\nfailed: %s." % (commandArgs,e.args[1]),file=sys.stderr)
            exitStatus = e.args[0]
         else:
            childPid   = child.pid
            childout   = child.stdout
            childoutFd = childout.fileno()
            childerr   = child.stderr
            childerrFd = childerr.fileno()

            outEOF = False
            errEOF = False

            while True:
               toCheck = []
               if not outEOF:
                  toCheck.append(childoutFd)
               if not errEOF:
                  toCheck.append(childerrFd)
               try:
                  # wait for input
                  ready = select.select(toCheck,[],[])
               except select.error:
                  ready = {}
                  ready[0] = []

               if childoutFd in ready[0]:
                  outChunk = os.read(childoutFd,bufferSize).decode('utf-8')
                  if outChunk == '':
                     outEOF = True
                  outData.append(outChunk)
                  if streamOutput and outChunk:
                     print(outChunk,end='')

               if childerrFd in ready[0]:
                  errChunk = os.read(childerrFd,bufferSize).decode('utf-8')
                  if errChunk == '':
                     errEOF = True
                  errData.append(errChunk)
                  if streamOutput and errChunk:
                     print(errChunk,end='',file=sys.stderr)

               if outEOF and errEOF:
                  break

            pid,exitStatus = os.waitpid(childPid,0)
            if exitStatus != 0:
               if   os.WIFSIGNALED(exitStatus):
                  if reportErrorExit:
                     print("%s failed w/ signal %d" % (commandArgs,os.WTERMSIG(exitStatus)),file=sys.stderr)
               else:
                  if os.WIFEXITED(exitStatus):
                     exitStatus = os.WEXITSTATUS(exitStatus)
                  if reportErrorExit:
                     print("%s failed w/ exit code %d" % (commandArgs,exitStatus),file=sys.stderr)
               if not streamOutput:
                  if reportErrorExit:
                     print("%s" % ("".join(errData)),file=sys.stderr)

         if stdin:
            fpStdin.close()

      return(exitStatus,"".join(outData),"".join(errData))


   def checkTrustedUserCache(self,simToolLocation):
      try:
         del os.environ['SIM2L_CACHE_SQUID']
      except:
         pass

      print("Checking for cached result")
      try:
           # Use HTTP cache client instead of ionhelper script
           cache_client = CacheClient()
        
           # Load inputs from file
           with open(self.inputsPath, 'r') as fp:
               import yaml
               inputs = yaml.safe_load(fp)
        
           # Get squid ID for these inputs
           try:
               squid_id = cache_client.get_squid_id(
                   simToolLocation['simToolName'],
                   simToolLocation['simToolRevision'],
                   inputs
               )
            
               # Check if this squid exists in cache
               if cache_client.check_squid_exists(squid_id):
                   exitCode = 0
                   # Retrieve the cached result
                   if cache_client.get_archived_result(squid_id, self.outdir):
                       os.environ['SIM2L_CACHE_SQUID'] = squid_id
                       exitCode = 0
                   else:
                       exitCode = 1
               else:
                   exitCode = 1
           except CacheClientException as e:
               print(f"Cache operation failed: {e}", file=sys.stderr)
               exitCode = 1
      except:
         exitCode = 1
         print(traceback.format_exc(),file=sys.stderr)
      else:
         if exitCode == 0:
            print("Found cached result = %s" % (os.environ.get('SIM2L_CACHE_SQUID','squidId does not exist')))
            if 'SIM2L_CACHE_SQUID' in os.environ:
               try:
                    squid_id = os.environ['SIM2L_CACHE_SQUID']
                    sim2LName,sim2LRevision,runHash = squid_id.split('/')
               except:
                  pass
               else:
                    self.squidId = squid_id

      self.cached = exitCode == 0


   def doTrustedUserRun(self,simToolLocation,
                             remoteAttributes=None):
      if remoteAttributes:
# pass along remote submit command arguments: venue, walltime, cores, command
         argumentsPath = os.path.join(self.outdir,'remoteArguments.json')
         with open(argumentsPath,'w') as fp:
            json.dump(remoteAttributes,fp)

      print("Executing simTool")
      try:
         # Use HTTP cache client to run simtool
         cache_client = CacheClient()
         
         try:
            result = cache_client.run_simtool(
               simToolLocation['simToolName'],
               simToolLocation['simToolRevision'],
               self.inputsPath
            )
            
            if result.get('success'):
               exitCode = 0
               os.environ['SIM2L_CACHE_SQUID'] = result.get('squid_id', '')
            else:
               exitCode = 1
         except CacheClientException as e:
            print(f"SimTool execution via cache server failed: {e}", file=sys.stderr)
            exitCode = 1
      except:
         exitCode = 1
         print(traceback.format_exc(),file=sys.stderr)
      else:
         if exitCode != 0:
            print("SimTool execution failed")
      self.cached = exitCode == 0
      if self.cached:
         try:
            squid_id = os.environ.get('SIM2L_CACHE_SQUID', '')
            sim2LName,sim2LRevision,runHash = squid_id.split('/')
         except:
            pass
         else:
            self.squidId = squid_id


   def retrieveTrustedUserResults(self,simToolLocation):
      if self.cached:
#        Retrieve result from cache
         print("Fetching cached result")
         try:
            # Use HTTP cache client to retrieve results
            cache_client = CacheClient()
            squid_id = os.environ.get('SIM2L_CACHE_SQUID', '')
            
            if squid_id:
               if cache_client.get_archived_result(squid_id, self.outdir):
                  exitCode = 0
               else:
                  exitCode = 1
            else:
               print("No squid ID available", file=sys.stderr)
               exitCode = 1
         except:
            exitCode = 1
            print(traceback.format_exc(),file=sys.stderr)
         else:
            if exitCode != 0:
               print("Retrieval of generated cached result failed")
      else:
#        Retrieve error result from ionhelper delivery
         print("Fetching error result")
         try:
            # Error result retrieval - would need to be implemented in cache server
            # For now, we'll skip this step as it's handled differently with HTTP cache
            print("Error result handling not yet implemented for HTTP cache", file=sys.stderr)
            exitCode = 1
         except:
            exitCode = 1
            print(traceback.format_exc(),file=sys.stderr)
         else:
            if exitCode != 0:
               print("Retrieval of failed execution result failed")
   def processOutputs(self,cache,prerunFiles,
                           trustedExecution=False):
      self.db = DB(self.outname,dir=self.outdir)
      if not trustedExecution:
         self.savedOutputs     = self.db.getSavedOutputs()
         self.savedOutputFiles = self.db.getSavedOutputFiles()
#        if len(self.savedOutputFiles) > 0:
#           print("Saved output files: %s" % (self.savedOutputFiles))

         requiredOutputs  = set(self.outputNames)
         deliveredOutputs = set(self.savedOutputs)
         missingOutputs = requiredOutputs - deliveredOutputs
         extraOutputs   = deliveredOutputs - requiredOutputs
         if 'simToolSaveErrorOccurred' in extraOutputs:
            extraOutputs.remove('simToolSaveErrorOccurred')
         if 'simToolAllOutputsSaved' in extraOutputs:
            extraOutputs.remove('simToolAllOutputsSaved')
         if len(missingOutputs) > 0:
            print("The following outputs are missing: %s" % (list(missingOutputs)))
         if len(extraOutputs) > 0:
            print("The following additional outputs were returned: %s" % (list(extraOutputs)))

#        simToolSaveErrorOccurred = self.db.getSimToolSaveErrorOccurred()
#        print("simToolSaveErrorOccurred = %d" % (simToolSaveErrorOccurred))
#        simToolAllOutputsSaved = self.db.getSimToolAllOutputsSaved()
#        print("simToolAllOutputsSaved = %d" % (simToolAllOutputsSaved))

         if cache:
            self.dstore.write_cache(self.outdir,prerunFiles,self.savedOutputFiles)


   def getResultSummary(self):
      return self.db.nb.scrap_dataframe


   def read(self, name, display=False, raw=False):
      return self.db.read(name,display,raw)


   def delete(self):
      if self.outdir:
         try:
            outdir = os.path.join(get_experiment(),self.runName)
         except:
            pass
         else:
            if outdir == self.outdir:
               shutil.rmtree(self.outdir,True)

      self.nbName           = ""
      self.inputs           = None
      self.input_dict       = None
      self.inputFiles       = None
      self.outputNames      = None
      self.runName          = ""
      self.outname          = ""
      self.outdir           = ""
      self.remoteSimTool    = ""
      self.cached           = False
      self.squidId          = ""
      self.dstore           = None
      self.inputsPath       = ""
      self.db               = None
      self.savedOutputFiles = None
      self.savedOutputs     = None


class LocalRun(RunBase):
   """
   Run a notebook without using submit.
   """

   def __init__(self,simToolLocation,inputs,runName,cache):
      RunBase.__init__(self,simToolLocation,inputs,runName,cache,
                            createOutDir=True,remoteAttributes=None,
                            remote=False,trustedExecution=False)

      if not self.cached:
         self.setupInputFiles(simToolLocation,
                              doSimToolFiles=True,keepSimToolNotebook=False,remote=False,
                              doUserInputFiles=True,
                              doSimToolInputFile=False)

         prerunFiles = os.listdir(self.outdir)
         prerunFiles.append(self.nbName)

         # FIXME: run in background. wait or check status.
         # Suppress
         # FutureWarning: Method cleanup(connection_file=True) is deprecated, use cleanup_resources(restart=False).
         with warnings.catch_warnings():
            warnings.simplefilter(action='ignore',category=FutureWarning)
            pm.execute_notebook(simToolLocation['notebookPath'],self.outname,parameters=self.input_dict,cwd=self.outdir)

         self.processOutputs(cache,prerunFiles,trustedExecution=False)
      else:
         self.db = DB(self.outname,dir=self.outdir)


class SubmitLocalRun(RunBase):
   """
   Run a notebook using submit --local.
   """

   def __init__(self,simToolLocation,inputs,runName,cache):
      RunBase.__init__(self,simToolLocation,inputs,runName,cache,
                            createOutDir=True,remoteAttributes=None,
                            remote=False,trustedExecution=False)

      if not self.cached:
         self.setupInputFiles(simToolLocation,
                              doSimToolFiles=True,keepSimToolNotebook=False,remote=False,
                              doUserInputFiles=True,
                              doSimToolInputFile=True)

         cwd = os.getcwd()
         os.chdir(self.outdir)

         prerunFiles = os.listdir(os.getcwd())
         prerunFiles.append(self.nbName)

         # FIXME: run in background. wait or check status.
         submitCommand = SubmitCommand()
         submitCommand.setLocal()
         submitCommand.setCommand(papermillCLI)
         submitCommand.setCommandArguments(["--no-request-save-on-cell-execute",
                                            "--autosave-cell-every","0",
                                            "--no-use-black-format-injection",
                                            "--parameters_file","inputs.yaml",
                                            simToolLocation['notebookPath'],
                                            self.nbName])
         submitCommand.show()
         try:
            result = submitCommand.submit()
         except:
            exitCode = 1
            print(traceback.format_exc(),file=sys.stderr)
         else:
            exitCode = result['exitCode']
            if exitCode != 0:
               print("SimTool execution failed")

         os.chdir(cwd)

         self.processOutputs(cache,prerunFiles,trustedExecution=False)
      else:
         self.db = DB(self.outname,dir=self.outdir)


class SubmitRemoteRun(RunBase):
   """
   Run a notebook using submit --venue VENUE -w TIME -n CORES.
   """

   def __init__(self,simToolLocation,inputs,runName,remoteAttributes,cache):
      RunBase.__init__(self,simToolLocation,inputs,runName,cache,
                            createOutDir=True,remoteAttributes=remoteAttributes,
                            remote=True,trustedExecution=False)

      if not self.cached:
         self.setupInputFiles(simToolLocation,
                              doSimToolFiles=True,keepSimToolNotebook=True,remote=True,
                              doUserInputFiles=True,
                              doSimToolInputFile=True)

         cwd = os.getcwd()
         os.chdir(self.outdir)

         prerunFiles = os.listdir(os.getcwd())
         prerunFiles.append(self.nbName)

         # FIXME: run in background. wait or check status.
         submitCommand = SubmitCommand()
         try:
            submitCommand.setVenue(remoteAttributes['venue'])
         except:
            pass
         try:
            submitCommand.setWallTime(remoteAttributes['wallTime'])
         except:
            pass
         try:
            submitCommand.setNcores(remoteAttributes['nCores'])
         except:
            pass
         submitCommand.setInputFiles([RunBase.SIMTOOLRUNPREFIX,RunBase.INPUTFILERUNPREFIX])
         submitCommand.setCommand(remoteAttributes['command'])
         submitCommand.setCommandArguments(["-s",simToolLocation['simToolName'],
                                            "-i","inputs.yaml"])
         submitCommand.show()
         try:
            result = submitCommand.submit()
         except:
            exitCode = 1
            print(traceback.format_exc(),file=sys.stderr)
         else:
            exitCode = result['exitCode']
            if exitCode != 0:
               print("SimTool execution failed")

         shutil.rmtree(self.remoteSimTool,True)

         os.chdir(cwd)

         self.processOutputs(cache,prerunFiles,trustedExecution=False)
      else:
         shutil.rmtree(self.remoteSimTool,True)
         self.db = DB(self.outname,dir=self.outdir)


class TrustedUserLocalRun(RunBase):
   """
   Prepare and run of a notebook as a trusted user.
   """

   def __init__(self,simToolLocation,inputs,runName,cache):
      if simToolLocation['published']:
# Only published simTool can be run with trusted user
         RunBase.__init__(self,simToolLocation,inputs,runName,cache,
                               createOutDir=True,remoteAttributes=None,
                               remote=False,trustedExecution=True)

         self.setupInputFiles(simToolLocation,
                              doSimToolFiles=False,keepSimToolNotebook=False,remote=False,
                              doUserInputFiles=True,
                              doSimToolInputFile=True)

         self.checkTrustedUserCache(simToolLocation)
         if not self.cached:
            self.doTrustedUserRun(simToolLocation,remoteAttributes=None)
            self.retrieveTrustedUserResults(simToolLocation)

         prerunFiles = None
         self.processOutputs(cache,prerunFiles,trustedExecution=True)
      else:
         print("The simtool %s/%s is not published" % (simToolLocation['simToolName'],simToolLocation['simToolRevision']))


class TrustedUserRemoteRun(RunBase):
   """
   Prepare and run of a notebook with remote execution as a trusted user.
   """

   def __init__(self,simToolLocation,inputs,runName,remoteAttributes,cache):
      if simToolLocation['published']:
# Only published simTool can be run with trusted user
         RunBase.__init__(self,simToolLocation,inputs,runName,cache,
                               createOutDir=True,remoteAttributes=remoteAttributes,
                               remote=True,trustedExecution=True)

         self.setupInputFiles(simToolLocation,
                              doSimToolFiles=True,keepSimToolNotebook=True,remote=True,
                              doUserInputFiles=True,
                              doSimToolInputFile=True)

         self.checkTrustedUserCache(simToolLocation)
         if not self.cached:
            self.doTrustedUserRun(simToolLocation,remoteAttributes=remoteAttributes)
            shutil.rmtree(self.remoteSimTool,True)
            self.retrieveTrustedUserResults(simToolLocation)
         else:
            shutil.rmtree(self.remoteSimTool,True)

         prerunFiles = None
         self.processOutputs(cache,prerunFiles,trustedExecution=True)
      else:
         print("The simtool %s/%s is not published" % (simToolLocation['simToolName'],simToolLocation['simToolRevision']))


class WebServicePrepare(RunBase):
   """
   Prepare notebook for web service execution.
   """

   def __init__(self,simToolLocation,inputs,runName,remoteAttributes,cache):
      if simToolLocation['published']:
# Only published simTool can be run with trusted user
         RunBase.__init__(self,simToolLocation,inputs,runName,cache,
                               createOutDir=False,remoteAttributes=remoteAttributes,
                               remote=True,trustedExecution=True)

         self.setupInputFiles(simToolLocation,
                              doSimToolFiles=True,keepSimToolNotebook=True,remote=True,
                              doUserInputFiles=True,
                              doSimToolInputFile=True)
      else:
         print("The simtool %s/%s is not published" % (simToolLocation['simToolName'],simToolLocation['simToolRevision']))


class Run:
   """Runs a SimTool.

       A copy of the SimTool will be created in the subdirectory with the same
       name as the current experiment.  It will be run with the provided inputs.

       If cache is True and the tool is published, the global cache will be used.
       If the tool is not published, and cache is True, a local user cache will be used.

       Args:
           simToolLocation: A dictionary containing information on SimTool notebook
               location and status.
           inputs: A SimTools Params object or a dictionary of key-value pairs.
           runName: An optional name for the run.  A unique name will be generated
               if no name is supplied.
           remoteAttributes: A list of parameters used for submission to offsite
               resource.  In the absence of remoteAttributes the notebook execution
               will occur locally.
           cache: If the SimTool was run with the same inputs previously, return
               the results from the cache.  Otherwise cache the results.  If this
               parameter is False, do neither of these.  The SimTool must be published
               to access the global cache, otherwise each user has a local cache
               that can be accessed.
           venue: [None, noSubmit, local, trustedLocal, remote, trustedRemote] venue selection mode.
               noSubmit - to ignore the presence of submit.
               local - to use 'submit --local'.
               trustedLocal - to use 'submit --local' as the trusted user for global cache interaction.
               remote - to use 'submit' to execute job on remote resource.
               trustedRemote - to use 'submit' to execute job on remote resource as the trusted user for global cache interaction.
               None - venue is determined based on the availability of submit and the other arguments.
       Returns:
           A Run object.
       """

   def __new__(cls,simToolLocation,inputs,runName=None,remoteAttributes=None,cache=True,venue=None):
      remoteRunAttributes = copy.deepcopy(remoteAttributes)
      if venue is None and submitAvailable:
         if   remoteRunAttributes:
            if simToolLocation['published'] and cache:
               venue = 'trustedRemote'
            else:
               venue = 'remote'
            if not 'command' in remoteRunAttributes:
               try:
                  nCores = remoteRunAttributes['nCores']
               except:
                  nCores = 1
               if nCores == 1:
                  remoteRunAttributes['command'] = "%s_simtool_serial" % (simToolLocation['simToolName'])
               else:
                  remoteRunAttributes['command'] = "%s_simtool_mpi" % (simToolLocation['simToolName'])
         elif simToolLocation['published'] and cache:
            venue = 'trustedLocal'
         else:
            venue = 'local'

      if simToolLocation['simToolRevision'] is None:
         cache = False

      if   venue == 'local':
         newclass = SubmitLocalRun(simToolLocation,inputs,runName,cache)
      elif venue == 'remote':
         newclass = SubmitRemoteRun(simToolLocation,inputs,runName,remoteRunAttributes,cache)
      elif venue == 'trustedLocal':
         newclass = TrustedUserLocalRun(simToolLocation,inputs,runName,cache)
      elif venue == 'trustedRemote':
         newclass = TrustedUserRemoteRun(simToolLocation,inputs,runName,remoteRunAttributes,cache)
      elif venue == 'noSubmit':
         newclass = LocalRun(simToolLocation,inputs,runName,cache)
      elif venue == 'webService': 
         newclass = WebServicePrepare(simToolLocation,inputs,runName,remoteRunAttributes,cache)
      elif venue is None:
         warnings.warn('import hubzero.submit.SubmitCommand failed',category=UserWarning)
         newclass = LocalRun(simToolLocation,inputs,runName,cache)
      else:
         raise ValueError('Bad venue/cache combination')

      return newclass


