# @package      hubzero-simtool
# @file         cachefetch.py
# @copyright    Copyright (c) 2019-2021 The Regents of the University of California.
# @license      http://opensource.org/licenses/MIT MIT
# @trademark    HUBzero is a registered trademark of The Regents of the University of California.
#
import sys
import os
import uuid
import copy
import shutil
import tempfile
import stat
import subprocess
import select
import traceback
import yaml
from .cache_client import CacheClient, CacheClientException
from .db import DB
from .experiment import get_experiment
from .utils import _get_inputs_dict, _get_extra_files, _get_inputFiles


class CachedRun:
   """Fetch sim2L results from global cache.

       Args:
           simToolLocation: A dictionary containing information on SimTool notebook
               location and status.
           inputs: A SimTools Params object or a dictionary of key-value pairs.
           runName: An optional name for the run.  A unique name will be generated
               if no name is supplied.
       Returns:
           A CachedRun object.
       """

   INPUTFILERUNPREFIX = '.notebookInputFiles'

   def __init__(self,simToolLocation,inputs=None,squidId=None,runName=None,createOutDir=True):
      self.nbName = simToolLocation['simToolName'] + '.ipynb'
      if inputs:
         self.inputs     = copy.deepcopy(inputs)
         self.input_dict = _get_inputs_dict(self.inputs,inputFileRunPrefix=CachedRun.INPUTFILERUNPREFIX)
         self.inputFiles = _get_inputFiles(self.inputs)
      else:
         self.inputs     = None
         self.input_dict = None
         self.inputFiles = None

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

      self.cached = False
      if squidId:
         self.squidId = '/'.join([simToolLocation['simToolName'],simToolLocation['simToolRevision'],squidId.split('/')[-1]])
      else:
         self.squidId = ""
      self.inputsPath = None
      self.db = None

      if simToolLocation['published']:
# Only published simTool can be run with trusted user
         if self.inputs:
            self.setupInputFiles(simToolLocation,
                                 doSimToolFiles=False,keepSimToolNotebook=False,
                                 doUserInputFiles=True,
                                 doSimToolInputFile=True)
         else:
            self.setupInputFiles(simToolLocation,
                                 doSimToolFiles=False,keepSimToolNotebook=False,
                                 doUserInputFiles=False,
                                 doSimToolInputFile=False)

         self.checkTrustedUserCache(simToolLocation)
         if not self.cached:
            print("The simtool %s/%s cached result not found" % (simToolLocation['simToolName'],simToolLocation['simToolRevision']))
         else:
            self.processOutputs()
      else:
         print("The simtool %s/%s is not published" % (simToolLocation['simToolName'],simToolLocation['simToolRevision']))


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
                            doSimToolFiles=True,keepSimToolNotebook=False,
                            doUserInputFiles=True,
                            doSimToolInputFile=True):
      if doSimToolFiles:
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

      if doUserInputFiles:
         inputFileRunPath = os.path.join(self.outdir,CachedRun.INPUTFILERUNPREFIX)
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
         if self.inputsPath and os.path.exists(self.inputsPath):
            with open(self.inputsPath, 'r') as fp:
               inputs = yaml.safe_load(fp)
         else:
            inputs = {}
         
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


   def processOutputs(self):
      self.db = DB(self.outname,dir=self.outdir)


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

      self.nbName     = ""
      self.inputs     = None
      self.input_dict = None
      self.inputFiles = None
      self.runName    = ""
      self.outname    = ""
      self.outdir     = ""
      self.cached     = False
      self.squidId    = ""
      self.inputsPath = ""
      self.db         = None


