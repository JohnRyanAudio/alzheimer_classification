#library imports
import pandas as pd
import numpy as np
# from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from boruta import BorutaPy
from itertools import compress
from datetime import datetime
import gc
import csv
import sys

def feature_selection(X_path, y_path, outdir, iterations = 1, rank_cutoff = 1, chunk_size=10000):

    with open(X_path, 'r') as f:
        header = f.readline().strip().split(',')

    # the 0th column are the row numbers
    feature_ids = np.arange(len(header)-1)
    num_chunks = max(1, round(len(feature_ids) / chunk_size))

    print("Number of chunks", num_chunks)
    print("Length of each chunk", chunk_size)

    #prepare feature_id sets for the first iteration
    feature_id_sets = np.array_split(np.random.permutation(feature_ids), num_chunks)

    #prepare targers
    y = pd.read_csv(y_path, header=None).values
    y = y[:,1]

    #prepare feature selection model
    rf = RandomForestClassifier(n_jobs=-1, class_weight='balanced', max_depth=5)
    feat_selector = BorutaPy(rf, max_iter= 100, n_estimators='auto', random_state=1)



    #start writing to a file
    header = ['iteration', 'run', 'feature_id', 'rank']
    with open(outdir, 'w', encoding='UTF8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for iteration in range(iterations):
            run = 1
            #generating new feature_id sets for each iteration
            feature_id_sets = np.array_split(np.random.permutation(feature_ids), num_chunks)
            for chunk_set in feature_id_sets:

                randomlist = list(chunk_set)

                print("Reading started for iteration " , iteration, "run ", run)
                #reading the subset of the dataset
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print("Start Time =", current_time)
                X = pd.read_csv(X_path, usecols=randomlist).values
                print("Reading done for iteration " , iteration, "run ", run)
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print("End Time =", current_time)

                #boruta fit
                feat_selector.fit(X, y)

                ## ranking ##
                ranks = feat_selector.ranking_
                feature_to_rank = {randomlist[i]: ranks[i] for i in range(len(randomlist)) if ranks[i]<=rank_cutoff}


                #writing to file
                for feature in feature_to_rank:
                    writer.writerow([iteration+1, run, feature, feature_to_rank[feature]])
                run+=1

                #delete whatever you dont need in the next run
                del feature_to_rank, ranks, X, randomlist
                #collect garbage
                gc.collect()

                # break
            iteration+=1
            # break

if __name__ == "__main__":

    # pass in './testing/matrices/X_chr19.csv' for X_path
    # pass in './testing/matrices/Y_chr.csv' for y_path
    # pass in './testing/matrices/feature_selection_results.csv' for outdir
    X_path = sys.argv[1]
    y_path = sys.argv[2]
    outdir = sys.argv[3]
    iterations = sys.argv[4]

    print('X_path: ', X_path)
    print('y_path: ', y_path)
    print('outdir: ', outdir)
    print("number of requested iterations", iterations)

    feature_selection(X_path, y_path, outdir, iterations)