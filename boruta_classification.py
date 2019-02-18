import ast
import boruta
from collections import Counter
import csv
import exceptions
import multiprocessing
import numpy as np
import pandas as pd
import random
from sklearn.ensemble import RandomForestClassifier
import sys

'''
See readme.txt for input, output and possible options.
'''


def pooling(chrlist, class_perc, dataset, outdir, pat, perc, r, run, subset, testpat):
    """
    Running function one_process for every chr on chrlist.
    Getting list of selected SNPs for every chromosome (returned by every process).
    Returning selected SNPs for class_perc as a dictionary named selected_snps (keys - chromosomes, values - numbers of SNPs).
    Writing number of selected SNPs for every chromosome for every perc to file named all_snps<run>.txt.
    """
    procs = []
    q = multiprocessing.Queue()
    qytrain = multiprocessing.Queue()
    if testpat:
        qytest = multiprocessing.Queue()
    else:
        qytest = None

    for ch in chrlist:

        p = multiprocessing.Process(target=one_process,
                                    args=(ch, class_perc, dataset, outdir, pat, perc, q, qytest, qytrain, r, run,
                                          subset, testpat))
        procs.append(p)
        p.start()

    for p in procs:
        p.join()

    selected_snps = {ch: None for ch in chrlist}
    all_snps = {p: 0 for p in perc}
    while q.qsize():
        qq = q.get()
        selected_snps[qq[0]] = qq[2]
        for j, p in enumerate(perc):
            all_snps[p] += qq[1][p]

    if qytest is None:
        params = [[qytrain, 'train']]
    else:
        params = [[qytrain, 'train'], [qytest, 'test']]
    for qy, type in params:
        yt = qy.get()
        while qy.qsize():
            vec = qy.get()
            if np.array_equal(vec, yt):
                pass
            else:
                raise exceptions.OtherError('Y %s matrix is different for different chromosomes!' % type)
        np.save('%sy_%s_%d.npy' % (outdir, type, run), yt)

    a = open('%sall_snps%d.txt' % (outdir, run), 'w')
    for p in perc:
        a.write('%d\t%d\n' % (p, all_snps[p]))
    a.close()

    return selected_snps


def one_process(ch, class_perc, dataset, outdir, pat, perc, q, qytest, qytrain, r, run, subset, testpat):
    """
    Loading data to matrices - function load_data.
    Selecting best SNPs subsets for every perc - function best_snps.
    Writing best SNPs for every chromosome into a file.
    Adding to multiprocessing-queue an element: [number of chromsome,
        dictionary - key: perc, value: selected SNPs by Boruta with perc.
    """

    print('Analysis for chromosome %d started\n' % ch)

    X, y, snp, Xtest, ytest = load_data(ch, dataset, outdir, pat, run, subset, testpat)

    print('matrices X and y for chromosome %d have been loaded\n' % ch)

    snps = best_snps(ch, perc, r, snp, X, y)

    print('best SNPs for chromosome %d have been selected by Boruta\n' % ch)

    if not snps[class_perc]:
        raise exceptions.OtherError('Warning: no SNPs were chosen from chromosome %d using Boruta with chosen class perc = %d' % (ch, class_perc))
    qytrain.put(y)
    np.save('%sX_train_chr%d_%d_%d.npy' % (outdir, ch, class_perc, run), X[:, snps[class_perc]])
    print('X train matrix for chr %d was saved to file' % ch)
    if testpat:
        qytest.put(ytest)
        np.save('%sX_test_chr%d_%d_%d.npy' % (outdir, ch, class_perc, run), Xtest[:, snps[class_perc]])

    ll = {p: 0 for p in perc}
    for p in perc:

        ll[p] = len(snps[p])

        lista = open('%sbestsnps_chr%d_%d_%d.txt' % (outdir, ch, p, run), 'w')
        lista.write('%d\n\n' % len(snps[p]))
        for el in snps[p]:
            lista.write('%d\n' % el)
        lista.close()

    print('process for chr %d finished\n' % ch)

    q.put([ch, ll, snps[class_perc]])


def load_data(ch, dataset, outdir, pat, run, subset, testpat):
    """
    Loading data from files into X and y matrices.
    Selection of patients not being in test set and SNPs present in subset-file.
    """

    snplist = {name: [] for name in dataset.keys()}
    if subset is not None:
        for name in dataset.keys():
            cc = open('%s%s_snps_chr%d.txt' % (dataset[name], subset, ch), 'r')
            for line in cc:
                snplist[name].append(int(line.split()[0]))
            cc.close()
        snp = len(snplist[name])
    else:
        if len(dataset) > 1:
            raise exceptions.NoParameterError('subset', 'There is more than one given data set, but subset of SNPs ' +
                                                        'is not given.')
        else:
            cc = open('%sgenome_stats.txt' % list(dataset.values())[0], 'r')
            snp = None
            for line in cc:
                if line.startswith('%d\t' % ch):
                    snp = int(line.split()[-1])
                    break
            cc.close()
            if 'snp' is None:
                raise exceptions.OtherError('There is no information about chromosome %d in %sgenome_stats.txt file'
                                            % (ch, list(dataset.values())[0]))
            snplist[list(dataset.keys())[0]] = list(range(snp))

    if testpat is None:
        testpat = []
    test = len(testpat)

    train_row = 0
    test_row = 0
    done = 0

    X_train = np.zeros(shape=(sum(pat.values()) - test, snp), dtype=np.int8)
    y_train = np.zeros(shape=(sum(pat.values()) - test,), dtype=np.int8)

    X_test = np.zeros(shape=(test, snp), dtype=np.int8)
    y_test = np.zeros(shape=(test,), dtype=np.int8)

    for name in dataset.keys():

        o = open('%sX_chr%d_nodif.csv' % (dataset[name], ch), 'r')
        reader = csv.reader(o, delimiter=',')
        next(reader)  # header

        y = pd.read_csv('%sY_chr.csv' % dataset[name], header=None, index_col=0).values
        y = y.ravel()

        # writing values from file to matrix X and Y

        for i, line in enumerate(reader):
            if (done + i) not in testpat:
                y_train[train_row] = y[i]
                for j, s in enumerate(snplist[name]):
                    X_train[train_row][j] = line[s + 1]
                train_row += 1
            else:
                y_test[test_row] = y[i]
                for j, s in enumerate(snplist[name]):
                    X_test[test_row][j] = line[s + 1]
                test_row += 1

        o.close()
        done += i + 1

    if testpat:
        return X_train, y_train, snp, X_test, y_test
    else:
        return X_train, y_train, snp, None, None


def best_snps(ch, perc, r, snp, X, y):
    s = snp // r
    snps = {a: [] for a in perc}

    for n in range(s + 1):

        if n != s:
            xx = X[:, n * r:n * r + r]
        elif n == s and snp % r != 0:
            xx = X[:, n * r:]

        for p in perc:
            result = run_boruta(xx, y, p)
            if not result:
                break
            else:
                snps[p] += [el + n * r for el in result]

    return snps


def run_boruta(X, y, p):
    rf = RandomForestClassifier(n_jobs=-1, class_weight='balanced', max_depth=5)
    feat_selector = boruta.BorutaPy(rf, n_estimators='auto', random_state=1, perc=p)
    feat_selector.fit(X, y)
    chosen = []
    for i, value in enumerate(feat_selector.support_):
        if value:
            chosen.append(i)
    return chosen


def read_typedata(chrlist, outdir, p, run, type):

    ch = chrlist[0]
    X = np.load('%sX_%s_chr%d_%d_%d.npy' % (outdir, type, ch, p, run))

    for ch in chrlist[1:]:

        X = np.concatenate((X, np.load('%sX_%s_chr%d_%d_%d.npy' % (outdir, type, ch, p, run))), axis=1)

    y = np.load('%sy_%s_%d.npy' % (outdir, type, run))

    return X, y


def build_testdata(chrlist, class_perc, selected_snps, testset):

    pat = patients(testset)
    for name in testset.keys():

        xx = np.zeros(shape=(pat[name], sum(list(map(len, selected_snps.values())))), dtype=np.int8)
        col = 0
        for ch in chrlist:
            o = open('%sX_chr%d_nodif.csv' % (testset[name], ch), 'r')
            reader = csv.reader(o, delimiter=',')
            next(reader)

            snps = selected_snps[ch]
            for i, line in enumerate(reader):
                xx[i][col:col+len(snps)] = [line[1:][ii] for ii in snps]

            col += len(snps)
            o.close()

        yy = pd.read_csv('%sY_chr.csv' % testset[name], header=None, index_col=0).values
        try:
            X_test = np.concatenate((X_test, xx), axis=0)
            y_test = np.concatenate((y_test, yy), axis=0)
        except NameError:
            X_test = xx
            y_test = yy

    return X_test, y_test


def classify(X_train, y_train, X_test, y_test):

    rf = RandomForestClassifier(n_estimators=500)
    rf.fit(X_train, y_train)
    return rf.score(X_train, y_train), rf.score(X_test, y_test)


def first_run(fixed, outdir, pat, run, testsize):

    run = establish_run('boruta', fixed, outdir, run)
    p = sum(pat.values())

    if testsize != 0:
        testpat = random.sample(range(p), int(p*testsize))
        ts = open('%stestpat_%d.txt' % (outdir, run), 'w')
        for el in testpat:
            ts.write('%d\n' % el)
        ts.close()
    else:
        testpat = None

    return run, testpat


def cont_run(chrlist, fixed, outdir, run):

    run_file = open('%sboruta_runs.txt' % outdir, 'r+')
    lines = run_file.readlines()
    towrite = ''
    occur = False
    for line in lines:
        if line.startswith(str(run) + '\t'):
            line = line.strip().split('\t')
            subset = line[3]
            testsize = float(line[4])
            perc = ast.literal_eval(line[5])
            if isinstance(perc, int):
                perc = [perc]
            r = int(line[6])
            chrs = read_chrstr(line[-1]) + chrlist
            for key, value in Counter(chrs).items():
                if value > 1:
                    if not fixed:
                        print("WARNING: chromosome %d has already been analysed in this run, so it was omited. " % key +
                              "If you want to analyse it anyway, please add '-fixed' attribute")
                        chrlist.remove(key)
                        if not chrlist:
                            raise exceptions.WrongValueError('chrlist', chrlist,
                                                             'There are no chromosomes to analyze!!!')
            chrs = list(set(chrs))
            chrs.sort()
            line[-1] = make_chrstr(chrs)
            strin = ''
            for el in line:
                strin += str(el) + '\t'
            strin += '\n'
            line = strin
            occur = True
        towrite += line
    run_file.close()

    if not occur:
        raise exceptions.WrongValueError('-run', str(run),
                                         'You set that it is a continuation, but this run has not been conducted yet.')

    if testsize != 0:
        ts = open('%stestpat_%d.txt' % (outdir, run), 'r')
        testpat = []
        for line in ts:
            testpat.append(int(line.strip()))
        ts.close()
    else:
        testpat = None

    return perc, r, subset, testpat, testsize, towrite


def establish_run(analysistype, fixed, outdir, run):

    try:
        run_file = open('%s%s_runs.txt' % (outdir, analysistype), 'r+')
        if run is None:
            run = 0
            runchanged = False
        else:
            runchanged = True
        lines = run_file.readline()  # header
        rr = []
        rewrite = False
        for line in run_file:
            try:
                val = int(line.split()[0])
            except ValueError:
                continue
            rr.append(val)
            if val != run:
                lines += line
            else:
                rewrite = True
        if rr:
            d = [i for i in range(1, max(rr)+2)]
            for el in rr:
                d.remove(el)
            if not runchanged:
                run = min(d)
                print('%s run number has been established! Run = %d' % (analysistype, run))
            elif rewrite:
                if not fixed:
                    raise exceptions.WrongValueError('-run', run,
                                                     "Run number %d has already been conducted (%s analysis)! "
                                                     % (run, analysistype) +
                                                     "If you want to overwrite it, please add '-fixed' atribute.")
                else:
                    run_file.seek(0)
                    run_file.write(lines)
                    run_file.truncate()
        else:
            if not runchanged:
                run = 1
                print('%s run number has been established! Run = %d' % (analysistype, run))

    except FileNotFoundError:
        run = 1
        run_file = open('%s%s_runs.txt' % (outdir, analysistype), 'w')
        if analysistype == 'boruta':
            run_file.write('run\tdata_set\tpatients\tsnps_subset\ttest_size\tperc\twindow_size\tchromosomes\n')
        elif analysistype == 'class':
            run_file.write('run\ttest_set\ttest_pat\ttrain_run\ttrain_set\ttrain_pat\tperc\tSNPs\tchromosomes\n')
        else:
            raise exceptions.OtherError('First line for %s run file is not defined!' % analysistype)
        print('%s run file has been made! Run number has been established! Run = %d' % (analysistype, run))

    run_file.close()

    return run


def make_chrstr(chrlist):

    cl = chrlist.copy()
    cl.append(0)
    chrstr = ''
    first = cl[0]
    och = first
    for ch in cl:
        if ch == och:
            och += 1
        elif first != och-1:
            if len(chrstr) != 0:
                chrstr += ', '
            chrstr += '%d-%d' % (first, och-1)
            first = ch
            och = ch+1
        else:
            if len(chrstr) != 0:
                chrstr += ', '
            chrstr += '%d' % first
            first = ch
            och = ch+1

    return chrstr


def read_chrstr(chrstr):

    chrstr = chrstr.strip('[]')
    c = chrstr.split(',')
    chrlist = []
    for el in c:
        el = el.split('-')
        if len(el) == 1:
            chrlist.append(int(el[0]))
        else:
            chrlist += [i for i in range(int(el[0]),int(el[1])+1)]
    chrlist.sort()

    return chrlist


def patients(dataset):

    pat = {name: 0 for name in dataset.keys()}
    for name in dataset.keys():
        g = open('%sgenome_stats.txt' % dataset[name], 'r')
        line = g.readline()
        p = int(line.split()[1])
        for line in g:
            if int(line.split()[1]) != p:
                raise exceptions.OtherError('Error: there is different number of patients for different chromosomes!')
        pat[name] = p
        g.close()
    return pat


perc = [90]
r = 5000
chrlist = [i for i in range(1, 24)]

dataset = {}
testset = {}
testsize = 0
class_only = False
boruta_only = False
borutarun = None
classrun = None
fixed = False
snp_subset = None
continuation = False

for q in range(len(sys.argv)):

    if sys.argv[q] == '-dataset':
        if sys.argv[q + 2][0] in ['.', '~', '/']:
            dataset[sys.argv[q+1]] = sys.argv[q + 2]
        else:
            raise exceptions.NoParameterError('directory',
                                              'After name of data set should appear a directory to folder with it.')

    if sys.argv[q] == '-testset':
        if sys.argv[q + 2][0] in ['.', '~', '/']:
            testset[sys.argv[q+1]] = sys.argv[q + 2]
        else:
            raise exceptions.NoParameterError('directory',
                                              'After name of test set should appear a directory to folder with it.')

    if sys.argv[q] == '-test':
        testsize = float(sys.argv[q + 1])

    if sys.argv[q] == '-perc':
        perc = ast.literal_eval(sys.argv[q + 1])
        if isinstance(perc, int):
            perc = [perc]

    if sys.argv[q] == '-classperc':
        class_perc = int(sys.argv[q + 1])

    if sys.argv[q] == '-subset':
        snp_subset = sys.argv[q + 1]

    if sys.argv[q] == '-r':
        r = int(sys.argv[q + 1])

    if sys.argv[q] == '-class':
        class_only = True

    if sys.argv[q] == '-boruta':
        boruta_only = True

    if sys.argv[q] == '-chr':
        chrlist = read_chrstr(sys.argv[q + 1])

    if sys.argv[q] == '-run':
        borutarun = int(sys.argv[q + 1])
        classrun = int(sys.argv[q + 1])

    if sys.argv[q] == '-borutarun':
        borutarun = int(sys.argv[q + 1])

    if sys.argv[q] == '-classrun':
        classrun = int(sys.argv[q + 1])

    if sys.argv[q] == '-fixed':
        fixed = True

    if sys.argv[q] == '-outdir':
        outdir = sys.argv[q + 1]

    if sys.argv[q] == '-cont':
        continuation = True


if 'outdir' not in globals():
    outdir = next(iter(dataset.values()))

if 'class_perc' not in globals():
    class_perc = perc[0]


if not class_only:

    # determination number of patient in given data set
    pat = patients(dataset)

    # determination of some parameters
    if not continuation:
        borutarun, testpat = first_run(fixed, outdir, pat, borutarun, testsize)
    else:
        perc, r, subset, testpat, testsize, towrite = cont_run(chrlist, fixed, outdir, borutarun)

    # running Boruta analysis
    selected_snps = pooling(chrlist, class_perc, dataset, outdir, pat, perc, r, borutarun, snp_subset, testpat)

    # saving information about done run to boruta_runs file
    if continuation:
        run_file = open('%sboruta_runs.txt' % outdir, 'w')
        run_file.write(towrite)
    else:
        run_file = open('%sboruta_runs.txt' % outdir, 'a')
        chrstr = make_chrstr(chrlist)
        run_file.write('%d\t%s\t%d\t%s\t%.1f\t%s\t%d\t%s\n' % (borutarun, ' + '.join(dataset.keys()), sum(pat.values()),
                                                               snp_subset, testsize, ','.join(list(map(str, perc))), r,
                                                               make_chrstr(chrlist)))
    run_file.close()


if not boruta_only:

    # reading training data from given run of boruta analysis
    X_train, y_train = read_typedata(chrlist, outdir, class_perc, borutarun, 'train')

    # determination of number of class run
    classrun = establish_run('class', fixed, outdir, classrun)

    # establishing testing data based on given test set(s) or test subset of patients
    if not testset:
        if testsize == 0:
            raise exceptions.NoParameterError('testset',
                                              'Test size was not given - define what set should be used as a testset.')
        X_test, y_test = read_typedata(chrlist, outdir, class_perc, borutarun, 'test')

    else:
        if class_only:
            selected_snps = {ch: [] for ch in chrlist}
            for ch in chrlist:
                o = open('%sbestsnps_chr%d_%d_%d.txt' % (outdir, ch, class_perc, borutarun), 'r')
                for i in range(2):  # header
                    o.readline()
                for line in o:
                    selected_snps[ch].append(int(line.strip()))
                o.close()
        X_test, y_test = build_testdata(chrlist, class_perc, selected_snps, testset)

    # running of classification
    score_train, score_test = classify(X_train, y_train, X_test, y_test)
    print('Classification done!')

    # saving scores to class_scores file
    trainpat, all_snps = X_train.shape
    testpat = y_test.shape[0]
    trainstr = ' + '.join(dataset.keys())
    if not testset:
        teststr = '%.1f*(%s)' % (testsize, trainstr)
    else:
        teststr = ' + '.join(testset.keys())
    scores_file = open('%sclass_scores_%d.txt' % (outdir, classrun), 'w', 1)
    scores_file.write('Random forest classification\n' +
                      'TRAINING DATA:\nData set =  %s\nPatients = %d\nSNPs = %d\nperc = %d\ntrain run = %d\n'
                      % (trainstr, trainpat, all_snps, class_perc, borutarun) +
                      'TESTING DATA:\nData set = %s\nPatients = %d\n'
                      % (teststr, testpat))
    scores_file.write('RESULT of ANALYSIS:\ntrain_score\ttest_score\n%.3f\t%.3f\n' % (score_train, score_test))
    scores_file.close()
    print('Scores saved to file')

    # writing information about class run to class_run file
    run_file = open('%sclass_runs.txt' % outdir, 'a')
    chrstr = make_chrstr(chrlist)
    'run\ttest_set\ttest_pat\ttrain_run\ttrain_set\ttrain_pat\tperc\tSNPs\tchromosomes\n'
    run_file.write('%d\t%s\t%d\t%d\t%s\t%d\t%d\t%d\t%s\n' % (classrun, teststr, testpat, borutarun, trainstr, trainpat,
                                                             class_perc, all_snps, chrstr))
    run_file.close()

    # saving matrices (on which was based the classification) to file
    for name in ['X_train', 'y_train', 'X_test', 'y_test']:
        np.save('%s%s_genome_%d.npy' % (outdir, name, classrun), eval(name))
