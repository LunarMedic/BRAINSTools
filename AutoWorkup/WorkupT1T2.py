#!/usr/bin/python
#################################################################################
## Program:   BRAINS (Brain Research: Analysis of Images, Networks, and Systems)
## Language:  Python
##
## Author:  Hans J. Johnson
##
##      This software is distributed WITHOUT ANY WARRANTY; without even
##      the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
##      PURPOSE.  See the above copyright notices for more information.
##
#################################################################################

import os
import csv
import sys
import string
import argparse
#"""Import necessary modules from nipype."""
#from nipype.utils.config import config
#config.set('logging', 'log_to_file', 'false')
#config.set_log_dir(os.getcwd())
#--config.set('logging', 'workflow_level', 'DEBUG')
#--config.set('logging', 'interface_level', 'DEBUG')
#--config.set('execution','remove_unnecessary_outputs','false')

from nipype.interfaces.base import CommandLine, CommandLineInputSpec, TraitedSpec, File, Directory
from nipype.interfaces.base import traits, isdefined, BaseInterface
from nipype.interfaces.utility import Merge, Split, Function, Rename, IdentityInterface
import nipype.interfaces.io as nio   # Data i/o
import nipype.pipeline.engine as pe  # pypeline engine
from nipype.interfaces.freesurfer import ReconAll

from nipype.utils.misc import package_check
#package_check('nipype', '5.4', 'tutorial1') ## HACK: Check nipype version
package_check('numpy', '1.3', 'tutorial1')
package_check('scipy', '0.7', 'tutorial1')
package_check('networkx', '1.0', 'tutorial1')
package_check('IPython', '0.10', 'tutorial1')

from BRAINSTools import *
from BRAINSTools.ANTSWrapper import *
from BRAINSTools.WarpAllAtlas import *
from BRAINSTools.ants.normalize import WarpImageMultiTransform

from WorkupT1T2AtlasNode import MakeAtlasNode

#############################################################################
#############################################################################
## Utility functions for the pipeline
#############################################################################
#############################################################################
def get_first_T1_and_T2(in_files,T1_count):
    '''
    Returns the first T1 and T2 file in in_files, based on offset in T1_count.
    '''
    return in_files[0],in_files[T1_count]

def GetExtensionlessBaseName(filename):
    '''
    Get the filename without the extension.  Works for .ext and .ext.gz
    '''
    import os
    currBaseName = os.path.basename(filename)
    currExt = os.path.splitext(currBaseName)[1]
    currBaseName = os.path.splitext(currBaseName)[0]
    if currExt == ".gz":
        currBaseName = os.path.splitext(currBaseName)[0]
        currExt = os.path.splitext(currBaseName)[1]
    return currBaseName


def get_list_element( nestedList, index ):
    return nestedList[index]

class AutoVivification(dict):
    """Implementation of perl's autovivification feature."""
    def __getitem__(self, item):
        try:
            return dict.__getitem__(self, item)
        except KeyError:
            value = self[item] = type(self)()
            return value

def getFirstT1(uid, dbfile):
    from cPickle import load
    with open(dbfile) as fp:
        db = load(fp)
    print("uid:= {0}, dbfile: {1}".format(uid,dbfile))
    print("result:= {0}".format(db[uid]["T1-30"]))
    return db[uid]["T1-30"][0]

def getT1s(uid, dbfile):
    from cPickle import load
    with open(dbfile) as fp:
        db = load(fp)
    #print("uid:= {0}, dbfile: {1}".format(uid,dbfile))
    #print("result:= {0}".format(db[uid]["T1-30"]))
    return db[uid]["T1-30"]

def getT1sLength(uid, dbfile):
    from cPickle import load
    with open(dbfile) as fp:
        db = load(fp)
    #print("uid:= {0}, dbfile: {1}".format(uid,dbfile))
    #print("result:= {0}".format(db[uid]["T1-30"]))
    return len(db[uid]["T1-30"])

def getT2s(uid, dbfile):
    from cPickle import load
    with open(dbfile) as fp:
        db = load(fp)
    #print("uid:= {0}, dbfile: {1}".format(uid,dbfile))
    #print("result:= {0}".format(db[uid]["T1-30"]))
    return db[uid]["T2-30"]

def getT1sT2s(uid, dbfile,altT1):
    from cPickle import load
    with open(dbfile) as fp:
        db = load(fp)
    #print("uid:= {0}, dbfile: {1}".format(uid,dbfile))
    #print("result:= {0}".format(db[uid]["T1-30"]))
    temp=db[uid]["T1-30"]
    temp.append(db[uid]["T2-30"])
    temp[0]=altT1
    return temp

def MakeList(firstElement,secondElement):
    return [firstElement, secondElement]

def createDBFile(subject_data_file,subjectDatabaseFile,mountPrefix):
    print "Building Subject List: " + subject_data_file
    subjData=csv.reader(open(subject_data_file,'rb'), delimiter=',', quotechar='"')
    myDB=dict()
    multiLevel=AutoVivification()  #This should be replaced by a more nested dictionary
    nestedDictionary=AutoVivification()
    for row in subjData:
        currDict=dict()
        validEntry=True
        if len(row) == 4:
            site=row[0]
            subj=row[1]
            session=row[2]
            rawDict=eval(row[3])
            currDict={}
            for imageType in rawDict.keys():
                fullPaths=[ mountPrefix+i for i in rawDict[imageType] ]
                if len(fullPaths) < 1:
                    print("Invalid Entry!  {0}".format(currDict))
                    validEntry=False
                for i in fullPaths:
                    if not os.path.exists(i):
                        print("Missing File: {0}".format(i))
                        validEntry=False
                currDict[imageType]=fullPaths
            currDict['site']=site
            currDict['subj']=subj

            if validEntry == True:
                myDB[session]=currDict
                UNIQUE_ID=site+"_"+subj+"_"+session
                nestedDictionary[site][subj][session]=currDict
                multiLevel[UNIQUE_ID]=currDict
        else:
            print "ERROR:  Invalid number of elements in row"
            print row
    print "DICTIONARY",multiLevel
    from cPickle import dump
    dump(multiLevel, open(subjectDatabaseFile,'w'))
    return multiLevel

###########################################################################
###########################################################################
###########################################################################
###########################################################################
###########################################################################
###########################################################################
## WorkupT1T2 is the main workflow to be run
###########################################################################
###########################################################################
###########################################################################
###########################################################################
###########################################################################
def WorkupT1T2(mountPrefix,ExperimentBaseDirectory, subject_data_file, atlas_fname_wpath, BCD_model_path,
               InterpolationMode="Linear", Mode=10,DwiList=[],WORKFLOW_COMPONENTS=[],CLUSTER_QUEUE=''):
    """
    Run autoworkup on all subjects data defined in the subject_data_file

    This is the main function to call when processing a data set with T1 & T2
    data.  ExperimentBaseDirectory is the base of the directory to place results, T1Images & T2Images
    are the lists of images to be used in the auto-workup. atlas_fname_wpath is
    the path and filename of the atlas to use.
    """
    subjectDatabaseFile=os.path.join( ExperimentBaseDirectory,'InternalWorkflowSubjectDB.pickle')
    multiLevel=createDBFile(subject_data_file,subjectDatabaseFile,mountPrefix)
    
    print "Building Pipeline"
    ########### PIPELINE INITIALIZATION #############
    baw200 = pe.Workflow(name="BAW_20120104_workflow")
    baw200.config['execution'] = {
                                     'plugin':'Linear',
                                     #'stop_on_first_crash':'true',
                                     #'stop_on_first_rerun': 'true',
                                     'stop_on_first_crash':'false',
                                     'stop_on_first_rerun': 'false',      ## This stops at first attempt to rerun, before running, and before deleting previous results.
                                     'hash_method': 'timestamp',
                                     'single_thread_matlab':'true',       ## Multi-core 2011a  multi-core for matrix multiplication.
                                     'remove_unnecessary_outputs':'false',
                                     'use_relative_paths':'false',         ## relative paths should be on, require hash update when changed.
                                     'remove_node_directories':'false',   ## Experimental
                                     'local_hash_check':'true',           ##
                                     'job_finished_timeout':15            ##
                                     }
    baw200.config['logging'] = {
      'workflow_level':'DEBUG',
      'filemanip_level':'DEBUG',
      'interface_level':'DEBUG',
      'log_directory': ExperimentBaseDirectory
    }
    baw200.base_dir = ExperimentBaseDirectory

    """TODO: Determine if we want to pass subjectID and scanID, always require full
    paths, get them from the output path, or something else.
    """
    uidSource = pe.Node(interface=IdentityInterface(fields=['uid']),name='99_siteSource')
    uidSource.iterables = ('uid', multiLevel.keys() )

    BAtlas = MakeAtlasNode(atlas_fname_wpath) ## Call function to create node
    
    ########################################################
    # Run ACPC Detect on first T1 Image - Base Image
    ########################################################
    BCD = pe.Node(interface=BRAINSConstellationDetector(), name="01_BCD")
    ##  Use program default BCD.inputs.inputTemplateModel = T1ACPCModelFile
    ##BCD.inputs.outputVolume =   "BCD_OUT" + "_ACPC_InPlace.nii.gz"                #$# T1AcpcImageList
    BCD.inputs.outputTransform =  "BCD" + "_Original2ACPC_transform.mat"
    BCD.inputs.outputResampledVolume = "BCD" + "_ACPC.nii.gz"
    BCD.inputs.outputLandmarksInInputSpace = "BCD" + "_Original.fcsv"
    BCD.inputs.outputLandmarksInACPCAlignedSpace = "BCD" + "_ACPC_Landmarks.fcsv"
    #BCD.inputs.outputMRML = "BCD" + "_Scene.mrml"
    BCD.inputs.interpolationMode = InterpolationMode
    BCD.inputs.houghEyeDetectorMode = 1  # Look for dark eyes like on a T1 image, 0=Look for bright eyes like in a T2 image
    BCD.inputs.acLowerBound = 80.0 # Chop the data set 80mm below the AC PC point.
    BCD.inputs.LLSModel = os.path.join(BCD_model_path,'LLSModel-2ndVersion.hdf5')
    BCD.inputs.inputTemplateModel = os.path.join(BCD_model_path,'T1-2ndVersion.mdl')

    # Entries below are of the form:
    baw200.connect( [ (uidSource, BCD, [(('uid', getFirstT1, subjectDatabaseFile) , 'inputVolume')] ), ])

    if 0 == 1:
        baw200DataSink=pe.Node(nio.DataSink(),name="baw200DS")
        baw200DataSink.inputs.base_directory=ExperimentBaseDirectory + "FinalRepository"
        baw200DataSink.inputs.regexp_substitutions = [
            ('foo/_uid_(?P=<project>PHD_[0-9][0-9][0-9])_(?P=<subject>[0-9][0-9][0-9][0-9])_(?P=<session>[0-9][0-9][0-9][0-9][0-9])','test/\g<project>/\g<subject>/\g<session>')
            ]
        baw200.connect(BCD, 'outputLandmarksInACPCAlignedSpace', baw200DataSink,'foo.@outputLandmarksInACPCAlignedSpace')
        baw200.connect(BCD, 'outputResampledVolume', baw200DataSink,'foo.@outputResampledVolume')
        baw200.connect(BCD, 'outputLandmarksInInputSpace', baw200DataSink,'foo.@outputLandmarksInInputSpace')
        baw200.connect(BCD, 'outputTransform', baw200DataSink,'foo.@outputTransform')
        baw200.connect(BCD, 'outputMRML', baw200DataSink,'foo.@outputMRML')
        """
    subs=r'test/\g<project>/\g<subject>/\g<session>'
pe.sub(subs,test)
pat=r'foo/_uid_(?P<project>PHD_[0-9][0-9][0-9])_(?P<subject>[0-9][0-9][0-9][0-9])_(?P<session>[0-9][0-9][0-9][0-9][0-9])'
pe=re.compile(pat)
pe.sub(subs,test)
test
test='foo/_uid_PHD_024_0003_12345'
pe.sub(subs,test)
pat=r'(?P<modulename>[^/]*)/_uid_(?P<project>PHD_[0-9][0-9][0-9])_(?P<subject>[0-9][0-9][0-9][0-9])_(?P<session>[0-9][0-9][0-9][0-9][0-9])'
subs=r'test/\g<project>/\g<subject>/\g<session>/\g<modulename>'
pe.sub(subs,test)
pe=re.compile(pat)
pe.sub(subs,test)
    """
    if 'BASIC' in WORKFLOW_COMPONENTS:
        ########################################################
        # Run BLI atlas_to_subject
        ########################################################
        BLI = pe.Node(interface=BRAINSLandmarkInitializer(), name="05_BLI")
        BLI.inputs.outputTransformFilename = "landmarkInitializer_atlas_to_subject_transform.mat"

        baw200.connect([
            (BCD,BLI,[('outputLandmarksInACPCAlignedSpace','inputFixedLandmarkFilename')]),
        ])
        baw200.connect([
            (BAtlas,BLI,[('template_landmarks_fcsv','inputMovingLandmarkFilename')]),
            (BAtlas,BLI,[('template_landmark_weights_csv','inputWeightFilename')])
        ])

    if 'AUXLMK' in WORKFLOW_COMPONENTS:
        ########################################################
        # Run BLI subject_to_atlas
        ########################################################
        BLI2Atlas = pe.Node(interface=BRAINSLandmarkInitializer(), name="05_BLI2Atlas")
        BLI2Atlas.inputs.outputTransformFilename = "landmarkInitializer_subject_to_atlas_transform.mat"

        baw200.connect([
            (BCD,BLI2Atlas,[('outputLandmarksInInputSpace','inputMovingLandmarkFilename')]),
        ])
        baw200.connect([
            (BAtlas,BLI2Atlas,[('template_landmarks_fcsv','inputFixedLandmarkFilename')]),
            (BAtlas,BLI2Atlas,[('template_landmark_weights_csv','inputWeightFilename')])
        ])
        Resample2Atlas=pe.Node(interface=BRAINSResample(),name="05_Resample2Atlas")
        Resample2Atlas.inputs.interpolationMode = "Linear"
        Resample2Atlas.inputs.outputVolume = "subject2atlas.nii.gz"

        baw200.connect( [ (uidSource, Resample2Atlas, [(('uid', getFirstT1, subjectDatabaseFile ), 'inputVolume')] ), ])
        baw200.connect(BLI2Atlas,'outputTransformFilename',Resample2Atlas,'warpTransform')
        baw200.connect(BAtlas,'template_t1',Resample2Atlas,'referenceVolume')

    if 'TISSUE_CLASSIFY' in WORKFLOW_COMPONENTS:
        from WorkupT1T2TissueClassifiy import CreateTissueClassifyWorkflow
        myLocalTCWF= CreateTissueClassifyWorkflow("11_TissueClassify",CLUSTER_QUEUE,InterpolationMode)
        baw200.connect( [ (uidSource, myLocalTCWF, [(('uid', getT1s, subjectDatabaseFile ), 'InputSpec.T1List')] ), ])
        baw200.connect( [ (uidSource, myLocalTCWF, [(('uid', getT2s, subjectDatabaseFile ), 'InputSpec.T2List')] ), ])
        baw200.connect( [ (uidSource, myLocalTCWF, [(('uid', getT1sLength, subjectDatabaseFile ), 'InputSpec.T1_count')] ), ])
        baw200.connect( BCD,    'outputResampledVolume', myLocalTCWF, 'InputSpec.PrimaryT1' )
        baw200.connect(BAtlas,'AtlasPVDefinition_xml',myLocalTCWF,'InputSpec.atlasDefinition')
        baw200.connect(BLI,'outputTransformFilename',myLocalTCWF,'InputSpec.atlasToSubjectInitialTransform')

        """
        ResampleNACLabels
        """
        ResampleAtlasNACLabels=pe.Node(interface=BRAINSResample(),name="13_ResampleAtlasNACLabels")
        ResampleAtlasNACLabels.inputs.interpolationMode = "NearestNeighbor"
        ResampleAtlasNACLabels.inputs.outputVolume = "atlasToSubjectNACLabels.nii.gz"

        baw200.connect(myLocalTCWF,'OutputSpec.atlasToSubjectTransform',ResampleAtlasNACLabels,'warpTransform')
        baw200.connect(myLocalTCWF,'OutputSpec.t1_corrected',ResampleAtlasNACLabels,'referenceVolume')
        baw200.connect(BAtlas,'template_nac_lables',ResampleAtlasNACLabels,'inputVolume')

        """
        BRAINSMush
        """
        BMUSH=pe.Node(interface=BRAINSMush(),name="15_BMUSH")
        BMUSH.inputs.outputVolume = "MushImage.nii.gz"
        BMUSH.inputs.outputMask = "MushMask.nii.gz"
        BMUSH.inputs.lowerThresholdFactor = 1.2
        BMUSH.inputs.upperThresholdFactor = 0.55

        baw200.connect(myLocalTCWF,'OutputSpec.t1_corrected',BMUSH,'inputFirstVolume')
        baw200.connect(myLocalTCWF,'OutputSpec.t2_corrected',BMUSH,'inputSecondVolume')
        baw200.connect(myLocalTCWF,'OutputSpec.outputLabels',BMUSH,'inputMaskVolume')

        """
        BRAINSROIAuto
        """
        BROI = pe.Node(interface=BRAINSROIAuto(), name="17_BRAINSROIAuto")
        BROI.inputs.closingSize=12
        BROI.inputs.otsuPercentileThreshold=0.01
        BROI.inputs.thresholdCorrectionFactor=1.0
        BROI.inputs.outputROIMaskVolume = "temproiAuto_t1_ACPC_corrected_BRAINSABC.nii.gz"
        baw200.connect(myLocalTCWF,'OutputSpec.t1_corrected',BROI,'inputVolume')

        """
        Split the implicit outputs of BABCext
        """
        SplitAvgBABC = pe.Node(Function(input_names=['in_files','T1_count'], output_names=['avgBABCT1','avgBABCT2'],
                                 function = get_first_T1_and_T2), run_without_submitting=True, name="99_SplitAvgBABC")
        SplitAvgBABC.inputs.T1_count = 1 ## There is only 1 average T1 image.

        baw200.connect(myLocalTCWF,'OutputSpec.outputAverageImages',SplitAvgBABC,'in_files')


        """
        Gradient Anistropic Diffusion images for BRAINSCut
        """
        GADT1=pe.Node(interface=GradientAnisotropicDiffusionImageFilter(),name="27_GADT1")
        GADT1.inputs.timeStep = 0.025
        GADT1.inputs.conductance = 1
        GADT1.inputs.numberOfIterations = 5
        GADT1.inputs.outputVolume = "GADT1.nii.gz"

        baw200.connect(SplitAvgBABC,'avgBABCT1',GADT1,'inputVolume')

        GADT2=pe.Node(interface=GradientAnisotropicDiffusionImageFilter(),name="27_GADT2")
        GADT2.inputs.timeStep = 0.025
        GADT2.inputs.conductance = 1
        GADT2.inputs.numberOfIterations = 5
        GADT2.inputs.outputVolume = "GADT2.nii.gz"

        def printFullPath(outFileFullPath):
            print("="*80)
            print("="*80)
            print("="*80)
            print("="*80)
            print("{0}".format(outFileFullPath))
            return outFileFullPath
        printOutImage = pe.Node( Function(function=printFullPath, input_names = ['outFileFullPath'], output_names = ['genoutFileFullPath']), run_without_submitting=True, name="99_printOutImage")
        baw200.connect( GADT2, 'outputVolume', printOutImage, 'outFileFullPath' )

        baw200.connect(SplitAvgBABC,'avgBABCT2',GADT2,'inputVolume')

        """
        Sum the gradient images for BRAINSCut
        """
        SGI=pe.Node(interface=GenerateSummedGradientImage(),name="27_SGI")
        SGI.inputs.outputFileName = "SummedGradImage.nii.gz"

        baw200.connect(GADT1,'outputVolume',SGI,'inputVolume1')
        baw200.connect(GADT2,'outputVolume',SGI,'inputVolume2')

        if 'SEGMENTATION' in WORKFLOW_COMPONENTS:
            pass
        
        ## Make deformed Atlas image space
        if 'ANTS' in WORKFLOW_COMPONENTS:
            many_cpu_sge_options_dictionary={'qsub_args': '-S /bin/bash -pe smp1 2-8 -l mem_free=5000M -o /dev/null -e /dev/null '+CLUSTER_QUEUE, 'overwrite': True}
            print("""Run ANTS Registration""")
            ComputeAtlasToSubjectTransform = pe.Node(interface=ANTSWrapper(), name="19_ComputeAtlasToSubjectTransform")
            ComputeAtlasToSubjectTransform.plugin_args=many_cpu_sge_options_dictionary
            ComputeAtlasToSubjectTransform.inputs.output_prefix = "ANTS_"

            baw200.connect( SplitAvgBABC,'avgBABCT1',ComputeAtlasToSubjectTransform,"fixed_T1_image")
            baw200.connect( SplitAvgBABC,'avgBABCT2',ComputeAtlasToSubjectTransform,"fixed_T2_image")
            baw200.connect( BAtlas,'template_t1',    ComputeAtlasToSubjectTransform,"moving_T1_image")
            baw200.connect( BAtlas,'template_t2',    ComputeAtlasToSubjectTransform,"moving_T2_image")
            baw200.connect(BLI,'outputTransformFilename',ComputeAtlasToSubjectTransform,'initialTransform')

            #####################
            #####################
            #####################
            WarpSubjectToAtlas = pe.Node(interface=WarpImageMultiTransform(), name = "20_WarpImageMultiTransform")
            WarpSubjectToAtlas.plugin_args=many_cpu_sge_options_dictionary
            WarpSubjectToAtlas.inputs.invert_affine=[0]   # only invert the transform at index 0
            WarpSubjectToAtlas.inputs.dimension=3
            WarpSubjectToAtlas.inputs.out_postfix='_To_Atlas'
            baw200.connect( SplitAvgBABC,'avgBABCT1',WarpSubjectToAtlas,"moving_image")
            baw200.connect( BAtlas,'template_t1', WarpSubjectToAtlas, 'reference_image')

            makeInverseTransformList = pe.Node(interface=Function(function=MakeList,
                                                                input_names=['firstElement','secondElement'],
                                                                output_names=['outList']),
                             run_without_submitting=True, name="99_MakeInverseTransformList")

            baw200.connect(BLI,'outputTransformFilename',makeInverseTransformList,'firstElement')
            baw200.connect(ComputeAtlasToSubjectTransform,'output_inversewarp',makeInverseTransformList,'secondElement')
            baw200.connect( makeInverseTransformList, 'outList',WarpSubjectToAtlas, 'transformation_series')

        if 'ANTSWARP_FIXME' in WORKFLOW_COMPONENTS:
            WarpAtlas = pe.Node(interface=WarpAllAtlas(), name = "19_WarpAtlas")
            WarpAtlas.inputs.moving_atlas = atlas_fname_wpath
            WarpAtlas.inputs.deformed_atlas = "./template_t2.nii.gz"
            #baw200.connect( ComputeAtlasToSubjectTransform,'output_affine', WarpAtlas,"affine_transform")
            baw200.connect(BLI,'outputTransformFilename',WarpAtlas,'affine_transform')
            baw200.connect( ComputeAtlasToSubjectTransform,'output_warp', WarpAtlas,"deformation_field")
            baw200.connect( SplitAvgBABC,'avgBABCT1', WarpAtlas, 'reference_image')

        if 'PERSISTANCE_CHECK' in WORKFLOW_COMPONENTS:
            from WorkupT1T2PERSISTANCE_CHECK import CreatePERSISTANCE_CHECKWorkflow
            myLocalPERSISTANCE_CHECKWF= CreatePERSISTANCE_CHECKWorkflow("999999_PersistanceCheckingWorkflow")
            PERSISTANCE_CHECKWF.connect(SplitAvgBABC,'avgBABCT1',myLocalPERSISTANCE_CHECKWF,'fixedVolume')
            PERSISTANCE_CHECKWF.connect(myLocalTCWF,'OutputSpec.outputLabels',myLocalPERSISTANCE_CHECKWF,'fixedBinaryVolume')
            PERSISTANCE_CHECKWF.connect(BAtlas,'template_t1',myLocalPERSISTANCE_CHECKWF,'movingVolume')
            PERSISTANCE_CHECKWF.connect(BAtlas,'template_brain',myLocalPERSISTANCE_CHECKWF,'movingBinaryVolume')
            PERSISTANCE_CHECKWF.connect(BLI,'outputTransformFilename',myLocalPERSISTANCE_CHECKWF,'initialTransform')

        if 'FREESURFER' in WORKFLOW_COMPONENTS:
            from WorkupT1T2FreeSurfer import CreateFreeSurferWorkflow
            myLocalFSWF= CreateFreeSurferWorkflow("Level1_FSTest")
            baw200.connect(uidSource,'uid',myLocalFSWF,'InputSpec.subject_id')
            baw200.connect(SplitAvgBABC,'avgBABCT1',myLocalFSWF,'InputSpec.T1_files')
            """
            baw200.connect(myLocalFSWF,'OutputSpec.subject_id',...)
            baw200.connect(myLocalFSWF,'OutputSpec.subject_dir',...)
            """
        else:
            print "Skipping freesurfer"
    return baw200
