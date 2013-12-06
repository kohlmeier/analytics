#!/usr/bin/env python
"""A script to look at assessments and determine if the student was trying
We take advantage of the fact that our assessments are adaptive, and so
students should be getting about half of the questions right, and shouldn't
get three in a row wrong.
"""
import string
import sys

MIN_NUM_RESPONSES = 8
USER_INDEX = 0
DT_INDEX = 1
EXERCISE_INDEX = 3
TIME_INDEX = 6
CORRECT_INDEX = 8

current_user = ''
current_responses = []

# The general strategy here is to accumulate all the attempts for a user,
# then to look at them and make sure they fulfill certain requirements (at
# least 8 questions and no three consecutive answered incorrectly)
for line in sys.stdin:
        user = line.split(',')[USER_INDEX]
        correct = line.split(',')[CORRECT_INDEX]
        if user != current_user:
            current_user = user
            if len(current_responses) >= MIN_NUM_RESPONSES:
                decent = True
                consecutive_wrongs = 0
                for r in current_responses:
                    if r.split(',')[CORRECT_INDEX] == 'false':
                        consecutive_wrongs += 1
                    else:
                        consecutive_wrongs = 0
                    if consecutive_wrongs >= 3:
                        decent = False
                        continue
                # If the conditions of the filtration are met,
                # we print the responses in simplified form
                if decent:
                    for r in current_responses:
                        r = r.split()
                        print string.join(
                            [r[USER_INDEX], r[DT_INDEX], r[EXERCISE_INDEX],
                            r[TIME_INDEX], r[CORRECT_INDEX]], ',')
            current_responses = []
        current_responses.append(line)
