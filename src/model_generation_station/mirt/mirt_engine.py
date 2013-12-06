import collections
import json
import numpy as np
import random
import sys

import engine
import mirt_util


class MIRTEngine(engine.Engine):

    REPEAT_MIN_CYCLE = 5  # don't repeat a question within 5 consecutive items
    ATTEMPT_MAX_TIMES = 1  # don't repeat exercises

    DEFAULT_MAX_LENGTH = 15

    # ===== BEGIN: Engine interface implementation =====
    def __init__(self, model_data, contextual_exercises=None):
        """
        Args:
            model_data: Either a rich object containing the actual model
                parameters, or a file name to points to an .npz file (for
                offline use only).
            contextual_exercises: a list of the exercises names that the
                client would like the engine to choose questions from.
        """

        in_offline_mode = isinstance(model_data, str)

        # Is it an old style (no response time) mirt?  If so, set the response
        # time couplings to 0.
        if 'couplings' in model_data:
            if not ('exercise_ind_dict' in model_data
                    and 'max_length' in model_data):
                raise engine.InvalidEngineParamsError()

            couplings = model_data['couplings']
            del model_data['couplings']
            model_data['num_abilities'] = couplings.shape[1] - 1
            num_exercises = len(model_data['exercise_ind_dict'])

            # convert into equivalent response-time
            # parameters
            theta = mirt_util.Parameters(
                model_data['num_abilities'], num_exercises)
            theta.W_correct[:, :] = couplings[:, :]
            theta.W_time[:, :] = 0.
            theta.sigma_time[:] = 1.
            model_data['theta_flat'] = theta.flat()

        if in_offline_mode:
            # we were passed a file name for a .npz file
            model_data = np.load(model_data)

            self.theta = model_data['theta'][()]
            self.exercise_ind_dict = model_data['exercise_ind_dict'][()]
        else:
            self.exercise_ind_dict = model_data['exercise_ind_dict']
            num_exercises = len(self.exercise_ind_dict)
            self.theta = mirt_util.Parameters(
                model_data['num_abilities'], num_exercises,
                vals=model_data['theta_flat'])

        self.num_abilities = self.theta.num_abilities
        self.abilities = np.zeros((self.num_abilities, 1))
        self.abilities_stdev = np.zeros((self.num_abilities, 1))

        if 'max_length' in model_data or not in_offline_mode:
            # Will throw an error if max_length is not set are we are
            # not in offline mode (i.e., passed an .npz file)
            self.max_length = model_data['max_length']

        else:
            # set a deafult if we are in offline mode, and max_length isn't set
            # TODO(jace): always set a default when generating the npz file,
            # and remove this code.
            self.max_length = MIRTEngine.DEFAULT_MAX_LENGTH

        if 'max_time_taken' in model_data:
            self.max_time_taken = model_data['max_time_taken']
        else:
            self.max_time_taken = 1000

        # random_item_frequency denotes the percentage of the time (past the
        # first question) that users are given a random question.
        if "random_item_frequency" in model_data:
            self.random_item_frequency = model_data["random_item_frequency"]
        else:
            self.random_item_frequency = .05

        self.contextual_exercises = contextual_exercises

    def next_suggested_item(self, history):
        """Return an ItemSuggestion for this Engine's preferred next item."""
        metadata = {}
        # we want to be sure we are only choosing from exercises the user has
        # not seen too recently or too often.
        eligible_exs = self._get_eligible_exercises(history)

        if not history or random.random() < self.random_item_frequency:
            # first question chosen randomly to avoid overuse of a single ex
            metadata["random"] = True

            # Find a random exercise that we haven't just seen
            ex = random.choice(eligible_exs)
        else:
            metadata["random"] = False
            # update ability estimates only once -- outside the loop
            self._update_abilities(history)

            max_info = float("-inf")
            max_info_ex = None
            for ex in eligible_exs:
                fi = self.fisher_information(history, ex)
                if fi > max_info:
                    max_info = fi
                    max_info_ex = ex
            ex = max_info_ex

        metadata["estimated_accuracy"] = self.estimated_exercise_accuracy(
                                    history, ex, False)

        return engine.ItemSuggestion(ex, metadata=metadata)

    def _filter_exercises_for_diversity(self, candidate_exs, history):
        """Given a history of items already selected and answered in this
        assessment, we filter a list of candidates exercises to avoid
        choosing an overly redundant exercise next.
        """
        # we treat exercises with the same root, like addition_1 and
        # addition_2, as similar.
        def get_root(name):
            end = name.rfind("_")
            root = name if end < 0 else name[:end]
            return root

        # Filter for diveristy w/r/t the attempt history so far.
        hist_roots = [get_root(engine.ItemResponse(h).exercise)
                      for h in history]
        root_histogram = collections.Counter(hist_roots)
        recent_roots = hist_roots[-MIRTEngine.REPEAT_MIN_CYCLE:]
        eligible_exs = [e for e in candidate_exs
                        if get_root(e) not in recent_roots and
                        root_histogram[get_root(e)] <
                        MIRTEngine.ATTEMPT_MAX_TIMES]
        return eligible_exs

    def _get_base_exercises(self):
        base_exs = self.exercises()
        return base_exs

    def _get_analytics_exercises(self, history):
        # TODO(jace) Would be nice to union with the live, mission
        # exercises, so we start getting data on brand new exercises. But
        # to do so we need to add logic that safely handles exercises
        # unknown in the model params during, say, _update_abilities.

        base_exs = self._get_base_exercises()
        return self._filter_exercises_for_diversity(base_exs, history)

    def _get_eligible_exercises(self, history):
        """Checks two heuristics to ensure diversity of questions used.
        Returns all sufficiently diverse exercises, or all exercises
        if none are diverse enough.
        """
        # Start with the list of all exercises known to the model.
        base_exs = self._get_base_exercises()

        # Filter for exs in the mission context, if they were provided.
        context_exs = base_exs[:]  # make a shallow copy
        if self.contextual_exercises:
            context_exs = set(self.contextual_exercises) & set(base_exs)
            context_exs = list(context_exs)

        # Filter for diveristy w/r/t the attempt history so far.
        eligible_exs = self._filter_exercises_for_diversity(
                context_exs, history)

        # Return the most aggressively filtered non-empty set.
        return eligible_exs or context_exs or base_exs

    def score(self, history):
        """Returns a float that is the overall score on this assessment.
        Caller beware: may not be useful of valid is the assessment if the
        assessment has not been fully completed.  Check if is_complete().
        """
        # use lots of steps when estimating score to make
        # the score seeem close to deterministic
        self._update_abilities(history, num_steps=1000)

        predicted_accuracies = np.asarray([
            self.estimated_exercise_accuracy(history, ex, False)
            for ex in self.exercises()], dtype=float)

        return np.mean(predicted_accuracies)

    def readable_score(self, history):
        score = self.score(history)
        return str(int(score * 100.0))

    def progress(self, history):
        return min(float(len(history)) / self.max_length, 1.0)

    def estimated_exercise_accuracy(self, history, exercise_name,
            update_abilities=True, ignore_analytics=False):
        """Returns the expected probability of getting a future question
        correct on the specified exercise.
        """
        if update_abilities:
            self._update_abilities(history, ignore_analytics=ignore_analytics)

        exercise_ind = mirt_util.get_exercises_ind(exercise_name,
                self.exercise_ind_dict)

        return mirt_util.conditional_probability_correct(
            self.abilities, self.theta, exercise_ind)[0]

    def estimated_exercise_accuracies(self, history):
        """Returns a dictionary where the keys are all the exercise names
        known by the engine to be in the domain.
        """
        # for efficiency update ability estimates only once -- outside the loop
        self._update_abilities(history)

        return {ex: self.estimated_exercise_accuracy(history, ex, False)
            for ex in self.exercises()}

    @staticmethod
    def validate_params(params):
        """Take a dictionary representing raw configuration parameters for
        an engine, validates them, peforms any type conversions that
        may be necessary, and return the cooked parameters. If the
        parameters are not valid, raises InvalidEngineParamsError.

        Note the data in params may be in one of two formats:
        1) The old format, which had no response time modeling, or
        2) A newer format, which models response times.

        Returns: dict
        """

        # These parameters are required for both formats.
        if not ('exercise_ind_dict' in params and 'max_length' in params):
            raise engine.InvalidEngineParamsError()

        if ('theta_flat' in params
                and 'num_abilities' in params
                and 'max_time_taken' in params):
            # We have everything required for the new format.
            params['theta_flat'] = np.array(params['theta_flat'])

        elif ('couplings' in params and
                len(params['couplings']) == len(params['exercise_ind_dict'])):
            # We have everything required for the old format.
            params['couplings'] = np.array(params['couplings'])

        else:
            raise engine.InvalidEngineParamsError()

        return params

    # ===== END: Engine interface implementation =====

    def fisher_information(self, history, exercise_name):
        """Compute Fisher information for exercise at current ability."""
        p = self.estimated_exercise_accuracy(history, exercise_name, False)

        # "discrimination" parameter for this exercise.  Note this
        # implementation is only valid for the single dimensional case.
        a = self.theta.W_correct[self.exercise_ind_dict[exercise_name], :-1]

        # TODO(jascha) double check this formula for the multidimensional case
        fisher_info = np.sum(a ** 2) * p * (1. - p)

        return fisher_info

    def exercises(self):
        return self.exercise_ind_dict.keys()

    def _update_abilities(self, history, use_mean=True, num_steps=200,
                          ignore_analytics=False):
        # TODO(jace) - check to see if history has actually changed
        # to avoid needless re-estimation
        # If ignore_analytics is true, only learn from non-analytics cards
        # This is to evaluate the quality of various models for predicting
        # the analytics card.
        if history and ignore_analytics:
            history = [
                h for h in history if h['metadata'] and
                not h['metadata'].get('analytics')]
        ex = lambda h: engine.ItemResponse(h).exercise
        exercises = np.asarray([ex(h) for h in history])
        exercises_ind = mirt_util.get_exercises_ind(
                exercises, self.exercise_ind_dict)

        is_correct = lambda h: engine.ItemResponse(h).correct
        correct = np.asarray([is_correct(h) for h in history]).astype(int)

        time_taken = lambda h: engine.ItemResponse(h).time_taken
        time_taken = np.asarray([time_taken(h) for h in history]).astype(float)
        # deal with out of range or bad values for the response time
        time_taken[~np.isfinite(time_taken)] = 1.
        time_taken[time_taken < 1.] = 1.
        time_taken[time_taken > self.max_time_taken] = self.max_time_taken
        log_time_taken = np.log(time_taken)

        sample_abilities, _, mean_abilities, stdev = (
                mirt_util.sample_abilities_diffusion(
                    self.theta, exercises_ind, correct, log_time_taken,
                    self.abilities, num_steps=num_steps))

        self.abilities = mean_abilities if use_mean else sample_abilities
        self.abilities_stdev = stdev


def interactive_test(test_engine):
    """A simple command line interface to the test_engine for manual testing."""

    # TODO(jace) this should a UserAssessment object. for now it is just
    # a tuple of (exercise, correct)
    history = []

    while not test_engine.is_complete(history):
        exercise = test_engine.next_suggested_item(history).item_id
        print "\nQuestion #%d, Exercise type: %s" % (len(history), exercise)
        correct = int(raw_input("Enter 1 for correct, 0 for incorrect: "))
        correct = correct if correct == 1 else 0
        response = engine.ItemResponse.new(correct, exercise,
                None, None, None, 10., None, None, None, None, None)
        history.append(response.data)
        print "Current score is now %.4f (stdev=%.4f." % (
                test_engine.score(history), test_engine.abilities_stdev)
        print "Progress is now %.4f." % test_engine.progress(history)

    print json.dumps(test_engine.estimated_exercise_accuracies(history),
                     indent=4)
    print test_engine.abilities
    print test_engine.score(history)


if __name__ == '__main__':
    if len(sys.argv) == 2:
        interactive_test(MIRTEngine(sys.argv[1]))
    else:
        exit("Usage: python %s npz_model_file" % sys.argv[0])

