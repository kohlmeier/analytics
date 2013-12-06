import numpy
import json
import engine
import mirt_engine


def load_and_simulate_assessment(
        json_file, roc_file, test_file, random_question=5, user_idx=0,
        exercise_idx=3, time_idx=6, correct_idx=8):
    """This function loads a json mirt file and a test file with example
    assessments to evaluate. Because Khan Academy selects the fifth yest
    item randomly from all test items, we use that item as an 'analytics
    card', and see what our model predicts as the accuracy on the fifth
    question given the other responses.

    Those accuracies and the ground truth are written to the file
    at roc_file, and used to evaluate the accuracy of the algorith, likely
    with a ROC curve ()

    TODO (eliana) Transform the data we save about assessments so that the
    indexes are in more logical locations
    """
    json.load(open(json_file, 'r'))
    params = json.load(open(json_file, 'r'))['params']
    outfile = open(roc_file, 'w')
    params['theta_flat'] = numpy.array(params['theta_flat'])
    test_data = open(test_file, 'r')
    model = mirt_engine.MIRTEngine(params)
    history = []
    user = ''
    count = 0
    last_ex = None
    last_correct = False
    model.only_live_exercises = False
    for line in test_data:
        new_user, ex, time, correct = parse_line(
            line, user_idx, exercise_idx, time_idx, correct_idx)
        # When we see a new user, reset the model and calculate our datapoint
        # if we have enough data.
        if user != new_user:
            if last_ex:
                write_roc_datapoint(
                    last_ex, last_correct, history, model, outfile)
            user = new_user
            model = mirt_engine.MIRTEngine(params)
            history = []
            count = 0
            last_ex = None
        count += 1
        if count == random_question:
            last_ex = ex
            last_correct = correct
        else:
            # TODO(eliana): Should we use a simplified
            # version of all the code so this sort of legacy happens less, or
            # should we use the version in the codebase so we don't have to
            # rewrite all the time?
            response = engine.ItemResponse.new(
                correct, ex, None, None, None, time,
                None, None, None, False, False, False)
        history.append(response.data)
    test_data.close()
    outfile.close()


def parse_line(line, user_idx, exercise_idx, time_idx, correct_idx):
    """Takes a line and the location of various critical fields within the line

    Returns the user, exercise, time taken, and whether the problem was
    answered correctly
    """
    line = line.split(',')
    user = line[user_idx]
    ex = line[exercise_idx]
    time = line[time_idx]
    correct = line[correct_idx] == 'true' or line[correct_idx] == 'True'
    return user, ex, time, correct


def write_roc_datapoint(last_ex, last_correct, history, model, outfile):
    """Prints datapoints in the format 1,.73 representing whether the student
    answered the question correctly, and how likely our model thought it was
    that they give the response they gave.
    """
    try:
        acc = model.estimated_exercise_accuracy(history, last_ex)
    except:
        return

    if last_correct:
        outfile.write('1,')
    else:
        outfile.write('0,')
    outfile.write(str(acc) + '\n')
