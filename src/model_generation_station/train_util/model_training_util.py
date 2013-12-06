import errno
import os
import random


def sep_into_train_and_test(
        infile_name, trainfile_name, testfile_name, test_portion=.1):
    infile = open(infile_name, 'r')
    train = open(trainfile_name, 'w')
    test = open(testfile_name, 'w')
    current_user = ''
    for line in infile:
        user = line.split(',')[0]
        if user != current_user:
            current_user = user
            if random.random() < test_portion:
                current_file = test
            else:
                current_file = train
        current_file.write(line)


def mkdir_p(paths):
    """Emulates mkdir -p; makes a directory and its parents, with no complaints
    if the directory is already present
    """
    if type(paths) == str:
        paths = [paths]
    for path in paths:
        path = os.path.expanduser(path)
        try:
            os.makedirs(path)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise
