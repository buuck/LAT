#!/usr/bin/env python3
import sys, imp
import tinydb as db
import numpy as np

import matplotlib as mpl
mpl.use('Agg')
sys.argv.append("-b")
import matplotlib.pyplot as plt
# plt.style.use('../pltReports.mplstyle')
from matplotlib.colors import LogNorm, Normalize

dsi = imp.load_source('dsi', '../dsi.py')
bkg = dsi.BkgInfo()
cal = dsi.CalInfo()
import waveLibs as wl


def main():

    # testStats()
    # plotStats()
    getCalRunTime()


def testStats():

    # load the last calibration run set in DS1 and figure out how many
    # counts we have in the m=2 s=238 population to work with.

    ds, calIdx = 1, 33
    calLo, calHi = 12726, 12733 # this is probably a lunchtime cal

    calDB = db.TinyDB("%s/calDB-v2.json" % dsi.latSWDir)
    pars = db.Query()

    # trap and HV thresholds for this calidx
    trapKey = "trapThr_ds1_m1_c33"
    trapVal = dsi.getDBRecord(trapKey,calDB=calDB,pars=pars)
    hvKey = "hvBias_ds1_m1_c33"
    hvVal = dsi.getDBRecord(hvKey,calDB=calDB,pars=pars)

    # pull thresh (keV) values for the bkgIdx closest to this calibration
    cLo, cHi = cal.GetCalRunCoverage("ds1_m1",calIdx)
    bkgRuns = bkg.getRunList(ds)
    bkgRanges = set()
    for run in bkgRuns:
        if cLo <= run <= cHi:
            bkgRanges.add( bkg.GetBkgIdx(ds, run) )
    bkgIdx = list(bkgRanges)[0] # it's 35

    # account for sub-ranges
    bkgRuns = bkg.getRunList(ds,bkgIdx)
    subRanges = bkg.GetSubRanges(ds,bkgIdx)
    if len(subRanges) == 0: subRanges.append((bkgRuns[0], bkgRuns[-1]))
    for subIdx, (runLo, runHi) in enumerate(subRanges):
        threshKey = "thresh_ds%d_bkg%d_sub%d" % (ds, bkgIdx, subIdx) # returns "thresh_ds1_bkg35_sub0"

    # load threshKeV values from bkg/auto-thrsh/db
    threshVal = dsi.getDBRecord(threshKey,calDB=calDB,pars=pars)
    chList = []
    print("DB results")
    for chan in sorted(threshVal):
        thrBad = threshVal[chan][2]
        if thrBad: continue
        thrMu = threshVal[chan][0]
        thrSig = threshVal[chan][1]
        thrKeV = thrMu + 3*thrSig
        print("%d  %.3f  %.3f  %d: %.3f keV" % (chan,thrMu,thrSig,thrBad,thrKeV))
        chList.append(chan)

    # ok, now let's load the cal runs themselves
    calRuns = cal.GetCalList("ds1_m1",calIdx)
    fileList = []
    for run in calRuns:
        latList = dsi.getSplitList("%s/latSkimDS%d_run%d*" % (dsi.calLatDir, ds, run), run)
        tmpList = [f for idx, f in sorted(latList.items())]
        fileList.extend(tmpList)

    # declare the output stuff
    evtIdx, evtSumET, evtHitE, evtChans = [], [], [], []
    thrCal = {ch:[] for ch in chList}

    # loop over LAT cal files
    from ROOT import TFile, TTree
    prevRun = 0
    evtCtr, totCtr, runTime = 0, 0, 0
    for iF, f in enumerate(fileList):

        print("%d/%d %s" % (iF, len(fileList), f))
        tf = TFile(f)
        tt = tf.Get("skimTree")

        # increment the run time and fill the output dict of thresholds
        tt.GetEntry(0)
        run = tt.run
        if run!=prevRun:
            start = tt.startTime_s
            stop = tt.stopTime_s
            runTime += stop-start

            # before applying thresholds (and getting sumET and mHT)
            # save them into the output dict (so we can compare w/ DB later).
            n = tt.Draw("channel:threshKeV:threshSigma","","goff")
            chan, thrM, thrS = tt.GetV1(), tt.GetV2(), tt.GetV3()
            tmpThresh = {}
            for i in range(n):
                if chan[i] not in chList:
                    continue
                if chan[i] in tmpThresh.keys():
                    continue
                thrK = thrM[i] + 3*thrS[i]
                tmpThresh[chan[i]] = [run,thrM[i],thrS[i],thrK]

            # fill the output dict
            for ch in tmpThresh:
                thrCal[ch].append(tmpThresh[ch]) # [run, thrM, thrS, thrK]

        prevRun = run

        # loop over tree
        for iE in range(tt.GetEntries()):
            tt.GetEntry(iE)
            if tt.EventDC1Bits != 0: continue
            totCtr += 1

            # calculate mHT and sumET

            n = tt.channel.size()
            chTmp = np.asarray([tt.channel.at(i) for i in range(n)])
            idxRaw = [i for i in range(tt.channel.size()) if tt.channel.at(i) in chList]
            hitERaw = np.asarray([tt.trapENFCal.at(i) for i in idxRaw])

            # get indexes of hits above threshold
            idxList = [i for i in range(tt.channel.size())
                if tt.channel.at(i) in chList
                and tt.trapENFCal.at(i) > threshVal[tt.channel.at(i)][0] + 3*threshVal[tt.channel.at(i)][1]
                and 0.7 < tt.trapENFCal.at(i) < 9999
                ]
            hitE = np.asarray([tt.trapENFCal.at(i) for i in idxList])

            mHT, sumET = len(hitE), sum(hitE)

            # for now, let's just grab m=2 s=238 evts.
            if mHT!=2: continue
            if not 237.28 < sumET < 239.46: continue

            hitChans = np.asarray([tt.channel.at(i) for i in idxList])

            # save event pairs to output
            evtIdx.append([run,iE])
            evtSumET.append(sumET)
            evtHitE.append(hitE)
            evtChans.append(hitChans)
            evtCtr += 1

    # output stats we got
    print("m2s238 evts:",evtCtr, "total evts:",totCtr, "runTime:",runTime)

    # save output
    np.savez("../plots/slo-m2s238-test.npz", evtIdx, evtSumET, evtHitE, evtChans, thrCal, evtCtr, totCtr, runTime)


def plotStats():

    # load data from testStats
    f = np.load('../plots/slo-m2s238-test.npz')
    evtIdx, evtSumET, evtHitE, evtChans = f['arr_0'], f['arr_1'], f['arr_2'], f['arr_3']
    thrCal = f['arr_4'].item()
    evtCtr, totCtr, runTime = f['arr_5'], f['arr_6'], f['arr_7']

    # load threshKeV values from bkg/auto-thrsh/db
    calDB = db.TinyDB("%s/calDB-v2.json" % dsi.latSWDir)
    pars = db.Query()
    threshDB = dsi.getDBRecord("thresh_ds1_bkg35_sub0",calDB=calDB,pars=pars)

    # throw a threshold warning if any det is above 1 keV (and by how much)
    for ch in thrCal:
        thrChan = np.asarray([val[3] for val in thrCal[ch]])
        thrMean, thrStd = np.mean(thrChan), np.std(thrChan)
        thrDB = threshDB[ch][0] + 3*threshDB[ch][1]
        errString = "Above 1" if thrMean > 1.0 else ""
        # print("ch %d  DB %.3f  CAL %.3f keV (%.3f), nRuns %d  %s" % (ch, thrDB, thrMean, thrStd, len(thrChan), errString))

    # fill hit arrays
    hitE, chan = [], []
    for iE in range(len(evtHitE)):
        hitE.extend(evtHitE[iE])
        chan.extend(evtChans[iE])

    # map channels
    chMap = list(sorted(set(chan)))
    chDict = {chMap[i]:i for i in range(len(chMap))}
    chan = [chDict[chan] for chan in chan]


    # -- plot 1 - hit E spectrum
    fig = plt.figure()

    xLo, xHi, xpb = 0, 250, 1
    x, hE = wl.GetHisto(hitE, xLo, xHi, xpb)

    plt.plot(x, hE, ls='steps', lw=1.5, c='b', label='m=2,s=238 hits')
    plt.xlabel("Energy (keV)", ha='right', x=1.)
    plt.ylabel("Counts", ha='right', y=1.)
    plt.legend(loc=1)
    plt.savefig("../plots/slo-hitE-test.png")


    # -- plot 2 - counts per channel vs E (2d), low-E region
    plt.cla()

    xLo, xHi, xpb = 0.5, 5, 0.2
    yLo, yHi = 0, len(chMap)
    nbx, nby = int((xHi-xLo)/xpb), len(chMap)

    h1,_,_ = np.histogram2d(hitE,chan,bins=[nbx,nby], range=[[xLo,xHi],[yLo,yHi]])
    h1 = h1.T
    im1 = plt.imshow(h1,cmap='jet')#,aspect='auto')#),vmin=hMin,vmax=hMax)#,norm=LogNorm())

    xticklabels = ["%.1f" % t for t in np.arange(0, 5.5, 0.5)]
    yticks = np.arange(0, len(chMap))
    plt.xlabel("Energy (keV)", ha='right', x=1.)
    plt.gca().set_xticklabels(xticklabels)

    plt.ylabel("channel", ha='right', y=1.)
    plt.yticks(yticks)
    plt.gca().set_yticklabels(chMap, fontsize=12)

    # note: can control z axis limits w/ code in LAT/sandbox/sea-plot.py
    fig.colorbar(im1, ax=plt.gca(), fraction=len(chMap)/941, pad=0.04)

    plt.tight_layout()
    plt.savefig("../plots/slo-fsVsHitE-test.png")


    # -- output: counts in each detector under 5 keV

    cLo, cHi, nbx = 0, len(chMap), len(chMap)
    x, hC = wl.GetHisto(chan, cLo, cHi, 1)

    hLow = [0]
    for idx,ch in enumerate(chMap):
        nTot = hC[idx+1] # 0-250 kev
        nLow = np.sum(h1[idx,:]) # 0-5 keV
        hLow.append(nLow)
        nCPB = nLow/(xHi-xLo)/xpb # avg counts per bin, assume flat for now.
        rTot = nTot/runTime
        rLow = nLow/runTime
        rCPB = nCPB/nbx/runTime   # counts/bin/runTime
        rt100Cts = (100/rCPB)/3600. if rCPB !=0 else -1
        print("rt %d  ch %d  rTot %.2f  rLow %.4f  rCPB %.4f / %.1f keV  need RT:%d hrs" % (runTime, ch, rTot, rLow, rCPB, xpb, rt100Cts))


    # -- plot 3 - counts per channel (1d), and a few different energy regions
    plt.cla()

    plt.bar(x-0.5, hC, 0.95, color='b', label='all hits %d-%d' % (0, 250))
    plt.bar(x-0.5, hLow, 0.95, color='r', label='hits %d-%d' % (xLo, xHi))

    plt.xlabel("channel", ha='right', x=1.)
    xticks = np.arange(0, len(chMap))
    plt.xticks(xticks)
    plt.gca().set_xticklabels(chMap, fontsize=12, rotation=90)

    plt.ylabel("Counts, mHT=2, sumET=238 hits", ha='right', x=1.)

    plt.legend(loc=1)
    plt.savefig("../plots/slo-chans-test.png")


def getCalRunTime():
    """
    Need to know the total run time of all cal runs in each DS.
    that's how we can predict the statistics before going through
    the trouble of a full scan over calibration data

    Rough prediction from plotStats:
    Need ~200 hours to get to 100 cts in every 0.2 keV bin.
    """
    from ROOT import GATDataSet, TFile, TTree, MJTRun

    for ds in [0,1,2,3,4,5]:

        runList = []

        # load standard cals
        for key in cal.GetKeys(ds):
            for sub in range(cal.GetIdxs(key)):
                runList.extend(cal.GetCalList(key,sub))
        print("DS",ds,"num standard cals:",len(runList))

        # load long cals
        lIdx = {0:[0], 1:[1], 2:[], 3:[2], 4:[3], 5:[5,6]}
        for l in lIdx[ds]:
            runList.extend(cal.GetSpecialRuns("longCal",l))
        runList = sorted(list(set(runList)))
        print("DS",ds,"num adding longcals:",len(runList))

        # use GDS once just to pull out the path.
        gds = GATDataSet()
        runPath = gds.GetPathToRun(runList[0],GATDataSet.kBuilt)
        filePath = '/'.join(runPath.split('/')[:-1])

        totCalRunTime = 0

        # get run time from built files (no tree loading)
        for iR, run in enumerate(runList):

            # print progress
            # if np.fabs(100*iR/len(runList) % 10) < 0.1:
                # print("%d/%d  run %d  RT %.2f hrs" % (iR, len(runList), run, totCalRunTime/3600))

            f = filePath+"/OR_run%d.root" % run
            tf = TFile(f)
            rInfo = tf.Get("run")
            start = rInfo.GetStartTime()
            stop = rInfo.GetStopTime()
            runTime = stop-start
            if runTime < 0 or runTime > 9999:
                print("error, run",run,"start",start,"stop")
                continue
            totCalRunTime += stop-start
            tf.Close()

        print("Total cal run time, DS%d: %.2f hrs." % (ds, totCalRunTime/3600))



if __name__=="__main__":
    main()