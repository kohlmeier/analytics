import argparse
import datetime
import multiprocessing
import os
import subprocess

from mirt import mirt_train_EM, mirt_npz_to_json, generate_predictions
from train_util import model_training_util

# Necessary on some systems to make sure all cores are used. If not all
# cores are being used and you'd like a speedup, pip install affinity
try:
    import affinity
    affinity.set_process_affinity_mask(0, 2 ** multiprocessing.cpu_count() - 1)
except:
    pass


def gen_data(script_dir, data_file, train_file, test_file, s3_access):
    """Optionally downloads data and splits into train and test files

    Downloads data if we want to download it from s3, otherwise
    accesses a dataset.

    Takes the downloaded data or the test data and separates it into a
    train and a test file.
    """
    if s3_access:
        print 'Downloading and filtering data'
        subprocess.call([script_dir +
            '/train_util/assessments/gen_data.sh',
            data_file,
            script_dir,
            '-xv'])

    print 'Separating data into train and test files'
    model_training_util.sep_into_train_and_test(
        data_file, train_file, test_file)


def get_command_line_arguments(arguments=None):
    """Gets command line arguments passed in when called, or
    can be called from within a programs.

    Parses input from the command line into options for running
    the MIRT model. For more fine-grained options, look at
    mirt_train_EM.py
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input",
        default=os.path.dirname(
            os.path.abspath(__file__)) + '/sample_data/all.responses',
        help=("Name of file where data of interest is lacated."))
    parser.add_argument(
        "-s", "--s3_access", action="store_true", default=False,
        help=("Whether the user is operating with s3 access. Probably only"
              " true of Khan Academy employees."))
    parser.add_argument(
        '-a', '--abilities', default=[1], type=int,
        nargs='+', help='The dimensionality/number of abilities.'
        'this can be a series of values for multiple models, ie. -a 1 2 3')
    parser.add_argument(
        '-t', '--train_with_time', action="store_true", default=False,
        help=("Whether to train with time (default=False). When this is"
              "selected, training without time is automatically turned off"
              "unless you also select -b (for training with and without time"))
    parser.add_argument(
        '-z', '--train_without_time', action="store_true", default=True,
        help=("Whether to train with time (default=True)"))
    parser.add_argument(
        '-b', '--train_with_and_without_time', action="store_true",
        default=False,
        help=("Trains multiple models with and without time. Double the"
              "models, double the fun."))
    parser.add_argument(
        '-w', '--workers', type=int, default=0,
        help=("The number of processes to use to parallelize mirt training"))
    parser.add_argument(
        "-n", "--num_epochs", type=int, default=100,
        help=("The number of EM iterations to do during learning"))
    parser.add_argument(
        "-o", "--output",
        default=os.path.dirname(
            os.path.abspath(__file__)) + '/sample_data/output/',
        help=("The directory to write output"))

    if arguments:
        arguments = parser.parse_args(arguments)
    else:
        arguments = parser.parse_args()

    # Calculates the arguments we want to go through viz-a-viz
    # training models and including time.
    if arguments.train_with_and_without_time:
        arguments.time_arguments = ['', '-z']
    elif arguments.train_with_time:
        arguments.time_arguments = ['']
    else:
        arguments.time_arguments = ['-z']

    return arguments


def main():
    arguments = get_command_line_arguments()
    run_with_arguments(arguments)


def run_with_arguments(arguments):
    """Takes you through every step from having a model, training it,
    testing it, and potentially uploading it to a testing engine.
    """

    # Set up directories
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mirt_dir = arguments.output + 'mirt/'
    data_file = os.path.expanduser(arguments.input)
    train_file = arguments.output + 'train.responses'
    test_file = arguments.output + 'test.responses'
    roc_dir = mirt_dir + 'rocs/'
    json_dir = mirt_dir + 'jsons/'
    model_training_util.mkdir_p([json_dir, mirt_dir, roc_dir])

    # Generate data, either by downloading from AWS or by providing your own
    # data from some other source
    gen_data(script_dir, data_file, train_file, test_file, arguments.s3_access)

    print 'Training MIRT models'
    datetime_str = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M")

    for abilities in arguments.abilities:
        for time in arguments.time_arguments:
            time_str = 'time' if time else 'no_time'
            param_str = "%s_%s_%s" % (abilities, time_str, datetime_str)
            outfilename = mirt_dir + param_str + '/'
            model_training_util.mkdir_p(outfilename)
            # to set more fine-grained parameters about MIRT training, look at
            # the arguments at mirt/mirt_train_EM.py
            mirt_train_params = [
                '-a', str(abilities),
                '-w', str(arguments.workers),
                '-n', str(arguments.num_epochs),
                '-f', train_file,
                '-o', outfilename]
            if time:
                mirt_train_params.append(time)
            mirt_train_EM.run_programmatically(mirt_train_params)

            npz_files = os.listdir(outfilename)
            npz_files.sort(key=lambda fname: fname.split('_')[-1])

            last_npz = outfilename + npz_files[-1]
            json_outfile = json_dir + param_str + '.json'
            mirt_npz_to_json.mirt_npz_to_json(
                last_npz, outfile=json_outfile, slug=param_str,
                title='math', description='math')
            roc_file = roc_dir + param_str + '.roc'
            generate_predictions.load_and_simulate_assessment(
                json_outfile, roc_file, test_file, user_idx=0,
                exercise_idx=2, time_idx=3, correct_idx=4)
    print
    print "If you're running this script somewhere you can't see"
    print "matplotlib, copy %s* to somewhere you" % roc_dir
    print "can see it, then run plot_roc_curves.py rocs/* from the"
    print "analytics repository on that machine."
    print
    print "Generated JSON MIRT models are in %s " % json_dir
    if arguments.s3_access:
        print ("Next step is to verify your model then upload to production,"
               "i.e., \n vi %s") % json_outfile
        print "%s/mirt_upload_to_gae.py --update %s" % (
            script_dir, json_outfile)
        print ("""
            To upload to a local dev_appserver, use curl on the json file:
            curl -H 'Content-Type: application/json --data @fracs.json
            http://localhost:8080/api/v1/dev/assessment/params?auth=off
             (where fracs.json is replaced with the appropriate json file name)
            """)

if __name__ == '__main__':
    main()
