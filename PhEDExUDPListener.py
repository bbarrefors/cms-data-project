#!/usr/bin/env python
"""
_PhEDExUDPListener_

This script recieves UDP packets with information from PhEDEx.
Packets contain information of files that have been accessed.
This information is stored i na local database and analyzed to
make decisions on when to subscribe a dataset.

Created by Bjorn Barrefors on 11/9/2013

Holland Computing Center - University of Nebraska-Lincoln
"""

import os
import socket
import ast
import re
import urllib2
import json
import time
import datetime
import sqlite3 as lite
from multiprocessing import Manager, Process, Pool

SET_ACCESS = 200
TOTAL_BUDGET = 40000
TIME_FRAME = 72
BUDGET_TIME_FRAME = 24

def datasetSize(dataset):
    """
    _datasetSize_
    
    Accumulate all block sizes and calculate total size of dataset in GB.
    In case of error in PhEDEx call return 0.
    """
    phedex_call = "http://cmsweb.cern.ch/phedex/datasvc/json/prod/data?dataset=" + str(dataset)
    try:
        response = urllib2.urlopen(phedex_call)
    except:
        return 0
    json_data = json.load(response)
    dataset = json_data.get('phedex').get('dbs')[0].get('dataset')[0].get('block')
    size_dataset = 0
    for block in dataset:
        size_dataset += block.get('bytes')

    size_dataset = size_dataset / 10**9
    return int(size_dataset)

def availableSpace():
    """
    _availableSpace_

    Return available space on phedex at UNL.
    Need to have at least 10% free at all times so return the space 
    available in GB to use without reaching 90% capacity.
    """
    info = os.statvfs("/mnt/hadoop")
    total = (info.f_blocks * info.f_bsize) / (1024**3)
    free = (info.f_bfree * info.f_bsize) / (1024**3)
    minimum_free = total*(0.1)
    available_space = free - minimum_free
    return int(avail_space_util)

def spaceCheck(dataset):
    """
    _spaceCheck_

    Check if dataset can be moved to datacenter 
    without going over the space limit.
    Return 0 fail and size of dataset if possible.
    """
    dataset_size = datasetSize(dataset)
    if (size_dataset == 0):
        return 0
    else:
        available_space = availableSpace()
        if (phedex_avail_util >= size_dataset):
            return int(size_dataset)
        else:
            return 0
    return 0

def subscriptionDecision():
    """
    _subscriptionDecision_

    Suggest subscription if a set have been accesses more than SET_ACCESS 
    and moving the set will not fill the new node more than 90%.
    """
    fs = open('/home/bockelman/barrefors/data.log', 'a')
    con = lite.connect("/home/bockelman/barrefors/dataset_cache.db")
    with con:
        cur = con.cursor()
        cur.execute('SELECT * FROM SetCount WHERE Count>=?', [SET_ACCESS])
        while True:
            row = cur.fetchone()
            if row == None:
                break
            dataset = row[0]
            fs.write(str(datetime.datetime.now()) + " Suggested data set: " + str(dataset) + " because it had " + str(setAccess) + " set accesses.\n")
            setAccess = row[1]
            cur.execute('SELECT * FROM DontMove WHERE Dataset=?', [dataset])
            row = cur.fetchone()
            if row:
                break

            budget = 0
            cur.execute('SELECT * FROM Budget')
            while True:
                row = cur.fetchone()
                if row == None:
                    break
                budget += row[1]
            dataset_size = spaceCheck(str(dataset))
            if (budget + dataset_size > TOTAL_BUDGET):
                break
            if (not (size == 0)):
                fs.write(str(datetime.datetime.now()) + " Move data set: " + str(dataset) + " because it had " + str(setAccess) + " set accesses.\n")
                cur.execute('INSERT OR IGNORE INTO DontMove VALUES(?)', [dataset])
                timestamp = datetime.datetime.now()
                delta = datetime.timedelta(hours=BUDGET_TIME_FRAME)
                expiration = timestamp + delta
                cur.execute('INSERT INTO Budget VALUES(?,?,?)', (dataset, int(dataset_size), expiration))
    con.close()
    fs.close()
    return 1

def update():
    """
    _update_

    Delete entries where the expiration timestamp is older than current time.
    Update SetCount to reflect database after deletions.
    Delete sets from SetCount if count is 0 or less.
    """
    con = lite.connect("/home/bockelman/barrefors/dataset_cache.db")
    with con:
        cur = con.cursor()
        cur.execute('SELECT Dataset FROM SetCount')
        while True:
            dataSet = cur.fetchone()
            if dataSet == None:
                break
            del_count = 0;
            cur.execute('DELETE FROM AccessTimestamp WHERE Expiration<? AND Dataset=?', (datetime.datetime.now(),dataSet[0]))
            del_count = cur.rowcount
            cur.execute('UPDATE SetCount SET Count=Count-? WHERE Dataset=?',(del_count, dataSet[0]))
            
        cur.execute('DELETE FROM FileToSet WHERE Expiration<?', [datetime.datetime.now()])
        minCount = 1
        cur.execute('DELETE FROM SetCount WHERE Count<?', [minCount])
        cur.execute('DELETE FROM UnknownSet WHERE Expiration<?', [datetime.datetime.now()])
        cur.execute('DELETE FROM Budget WHERE Expiration<?', [datetime.datetime.now()])
    con.close()
    return 1

def janitor():
    """
    _janitor_
    
    Run the janitor once every hour. 
    The janitor is in charge of cleaning out expired 
    entries in the database and suggest subscriptions.
    """
    Run every hour
    while True:
        time.sleep(3600)
        # Update database, delete entries older than 12h
        update()
        # Check if should make subscriptions
        subscriptionDecision()
    return 1

def dataHandler(d):
    """
    _dataHandler_

    Analyze dictionary extracted from UDP packet
    to insert dataset accesses in database.
    Dataset may not exist, record this as unknown.
    """
    con = lite.connect("/home/bockelman/barrefors/dataset_cache.db")
    lfn = str(d['file_lfn'])
    with con:
        cur = con.cursor()
        cur.execute("SELECT EXISTS(SELECT * FROM FileToSet WHERE File=?)", [lfn])
        test = cur.fetchone()[0]
        if int(test) == int(1):
            cur.execute('SELECT Dataset FROM FileToSet WHERE File=?', [lfn])
            dataset = cur.fetchone()[0]
            timestamp = datetime.datetime.now()
            delta = datetime.timedelta(hours=TIME_FRAME)
            expiration = timestamp + delta
            cur.execute('UPDATE SetCount SET Count=Count+1 WHERE Dataset=?', [dataset])
            cur.execute('UPDATE FileToSet SET Expiration=? WHERE File=?', (lfn, expiration))
            cur.execute('UPDATE AccessTimestamp SET Expiration=? WHERE Dataset=?', (expiration, dataset))
        else:
            phedex_call = "http://cmsweb.cern.ch/phedex/datasvc/json/prod/data?file=" + lfn
            try:
                response = urllib2.urlopen(phedex_call)
            except:
                return 0
            json_data = json.load(response)
            if json_data.get('phedex').get('dbs'):
                dataset = json_data.get('phedex').get('dbs')[0].get('dataset')[0].get('name')
                timestamp = datetime.datetime.now()
                delta = datetime.timedelta(hours=TIME_FRAME)
                expiration = timestamp + delta
                cur.execute('INSERT INTO AccessTimestamp VALUES(?,?)', (dataset, expiration))
                cur.execute('INSERT INTO FileToSet VALUES(?,?,?)', (lfn, dataset, expiration))
                cur.execute("SELECT EXISTS(SELECT * FROM SetCount WHERE Dataset=?)", [dataset])
                test = cur.fetchone()[0]
                if int(test) == int(1):
                    cur.execute('UPDATE SetCount SET Count=Count+1 WHERE Dataset=?', [dataset])
                else:
                    in_count = 1
                    cur.execute('INSERT INTO SetCount VALUES(?,?)', (dataset, in_count))
            else:
                # Unknown log
                delta = datetime.timedelta(hours=TIME_FRAME)
                timestamp = datetime.datetime.now()
                dataset = "UNKNOWN"
                cur.execute('INSERT OR IGNORE INTO UnknownSet VALUES(?,?,?)', (lfn, dataset, timestamp))
    con.close()
    return 1

def work(q):
    """
    _work_
    
    Distribute data handling of UDP packets to worker processes.
    """
    while True:
        d = q.get()
        dataHandler(d)

def dataParser(data):
    """
    _dataParser_
    
    Extract data from UDP packet and insert into dictionary.
    """
    d = {}
    for line in data.split('\n'):
        if '=' in line:
            k, v = line.strip().split('=',1)
            if v:
                d[k] = v
    return d

# TODO : Function for setting up database

# TODO : Function for parsing config file

if __name__ == '__main__':
    """
    __main__

    Parse config file and set parameters based on values.
    Set up database.
    Spawn worker processes and janitor.
    Recieve UDP packets and send to parser and then distribute to workers.
    """
    config_f = open('listener.conf', 'r')
    for line in config_f:
        if re.match("set_access", line):
            value = re.split(" = ", line)
            SET_ACCESS = int(value[1].rstrip())
        elif re.match("total_budget", line):
            value = re.split(" = ", line)
            TOTAL_BUDGET = int(value[1].rstrip())
        elif re.match("time_frame", line):
            value = re.split(" = ", line)
            TIME_FRAME = int(value[1].rstrip())
        elif re.match("budget_time_frame", line):
            value = re.split(" = ", line)
            BUDGET_TIME_FRAME = int(value[1].rstrip())
    config_f.close()

    # Create database and tables if they don't already exist
    connection = lite.connect("/home/bockelman/barrefors/dataset_cache.db")
    with connection:
        cur = connection.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS FileToSet (File TEXT, Dataset TEXT, Expiration TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS AccessTimestamp (Dataset TEXT, Expiration TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS SetCount (Dataset TEXT, Count INTEGER)')
        cur.execute('CREATE TABLE IF NOT EXISTS UnknownSet (File TEXT UNIQUE, Dataset TEXT, Expiration TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS Budget (Dataset TEXT, Size INTEGER, Expiration TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS DontMove (Dataset TEXT UNIQUE)')
        dataset = "/GenericTTbar/SAM-CMSSW_5_3_1_START53_V5-v1/GEN-SIM-RECO"
        cur.execute('INSERT OR IGNORE INTO DontMove VALUES(?)', [dataset])
        dataset = "/GenericTTbar/HC-CMSSW_5_3_1_START53_V5-v1/GEN-SIM-RECO"
        cur.execute('INSERT OR IGNORE INTO DontMove VALUES(?)', [dataset])
    
    # Spawn worker processes that will parse data and insert into database
    pool = Pool(processes=4)
    manager = Manager()
    queue = manager.Queue()

    # Spawn process that to clean out database and make reports every 1h
    process = Process(target=janitor, args=())
    process.start()
    workers = pool.apply_async(work, (queue,))

    # UDP packets containing information about file access
    UDPSock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    listen_addr = ("0.0.0.0", 9345)
    UDPSock.bind(listen_addr)
    buf = 64*1024

    # Listen for UDP packets
    try:
        while True:
            data,addr = UDPSock.recvfrom(buf)
            dictionary = dataParser(data)
            queue.put(dictionary)

    #Close everything if program is interupted
    finally:
        UDPSock.close()
        pool.close()
        pool.join()
        process.join()