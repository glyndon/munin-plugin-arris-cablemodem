#!/usr/bin/python3
"""
    Copyright 2017-2019 Gary Dobbins <gary@dobbinsonline.org>

    A Munin plugin that fulfills the work of several plugins (existing as uniquely-named links to this file)
    Operates in 3 modes: gather data, report as plugin, report config as plugin
    1) When called by its own name (i.e. by cron), it scrapes data from the Arris Cablemodem's status pages
    and stores the relevant values as a JSON file.
    2) When called by (arg[0]) the name of a plugin it emulates it reads the JSON file and reports the requested values.
    3) If 'config' is an arg, reports that plugin's config text.

    Munin will call us will be through links to us whose names indicate what plugin Munin thinks it's calling
    We can discern this from args[0], which will tell us what plugin to impersonate and report as.

    This version is attuned to the web interface of the Arris SB6183
"""

import time
import datetime
import json
import re
import textwrap
import subprocess
import urllib.request
import math
# import bs4
from bs4 import BeautifulSoup

jsonFile = '/tmp/wan.json'
speedtestJsonFile = '/tmp/speedtest.json'
report = {}
priorReport = {}
priorReportAvailable = False # a good idea, but not used/needed. numberOfMinutesElapsed tells the story.
numberOfMinutesElapsed = 0.0
uptimeSeconds = 0
modemStatusURL = 'http://192.168.100.1/'
modemUptimeURL = 'http://192.168.100.1/RgSwInfo.asp'
target_host = '8.8.4.4'
target_hops = 3

def calculateRates():
    global report, priorReport

def main(args):
    global report, priorReport, numberOfMinutesElapsed

    # If there's a 'config' param, then just emit the static config report for the name by which we were called
    if any('config' in word for word in args):
        reportConfig(args)
        return

    # report data as a plugin for the name by which we were called
    if any('downpower' in word for word in args):
        openInput(jsonFile)
        for chan in report['downpower']:
            print('down-power-ch'+chan+'.value', report['downpower'][chan])
        return

    if any('downsnr' in word for word in args):
        openInput(jsonFile)
        for chan in report['downsnr']:
            print('down-snr-ch'+chan+'.value', report['downsnr'][chan])
        return

    if any('uppower' in word for word in args):
        openInput(jsonFile)
        for chan in report['uppower']:
            print('up-power-ch'+chan+'.value', report['uppower'][chan])
        return

    if any('corrected' in word for word in args):
        openInput(jsonFile)
        try:
            for chan in report['corrected']:
                print('down-corrected-ch'+chan+'.value', report['corrected'][chan])
        except KeyError: # silently tolerate this section being absent
            pass
        return

    if any('uncorrectable' in word for word in args):
        openInput(jsonFile)
        try:
            for chan in report['uncorrectable']:
                print('down-uncorrectable-ch'+chan+'.value', report['uncorrectable'][chan])
        except KeyError: # silently tolerate this section being absent
            pass
        return

    if any('ping' in word for word in args):
        openInput(jsonFile)
        print( 'latency.value', report['next_hop_latency'] )
        return

    if any('speedtest' in word for word in args):
        openInput(speedtestJsonFile)
        downloadspeed = float(report['download'] / 1000000)
        uploadspeed = float(report['upload'] / 1000000)
        # distance = max( 0.0, float(report['server']['d'] - 3)) # drop a few miles so the lines on the graph don't coincide so much
        distance = math.log(max( 1, float(report['server']['d']) - 3)) + 10 # recompute the miles so the lines on the graph don't coincide so much
        print( 'down.value', downloadspeed )
        print( 'up.value', uploadspeed )
        print( 'distance.value', distance )
        return

    # ============================================================
    # in main()... This is the default logic that happens when called to update stored data
    # instead of reporting we scrape the modem, do some math and store the JSON

    reportDateTime() # get current time into the dictionary
    try: # fetch last-run's data and datetime
        fhInput = open(jsonFile, 'r')
        priorReport = json.load(fhInput)
        fhInput.close()

        # find the distance in time from when we last ran
        priorTime = datetime.datetime.fromisoformat(priorReport['datetime_utc'])
        currentTime = datetime.datetime.fromisoformat(report['datetime_utc'])
        numberOfMinutesElapsed = (currentTime - priorTime) / datetime.timedelta(minutes=1)
        priorReportAvailable = True
    except (FileNotFoundError, OSError, json.decoder.JSONDecodeError) as e:
        numberOfMinutesElapsed = 0
        priorReportAvailable = False

    getGateway() # determined by traceroute
    nextHopLatency() # measured by ping
    try: # get all the status data from the modem
        fhOutput = open(jsonFile, 'w')
        if (scrapeIntoReport(report) != 0): # spit out the timestamp when the attempt failed
            print("No Internet Connection as of (local time):")
            print(datetime.datetime.now().isoformat())
            # return
        calculateRates()
        json.dump(report, fhOutput, indent=2)
        fhOutput.close()
    except OSError:
        print("something went wrong creating", jsonFile)

def scrapeIntoReport(report):
    # global report, uptimeSeconds

    # Get the 'Up Time' quantity
    page = urllib.request.urlopen(modemUptimeURL).read()
    page = page.decode("utf-8") # convert bytes to str
    page = page.replace('\x0D', '') # strip out the unwanted newlines within the text
    soup = BeautifulSoup(str(page), 'html.parser') # this call takes a lot of time

    block = soup.find('td', string="Up Time")
    block = block.next_sibling # skip the header rows
    block = block.next_sibling
    uptimeText = block.get_text()
    uptimeElements = re.findall(r"\d+", uptimeText )
    uptimeSeconds  = int(uptimeElements[3])
    uptimeSeconds += int(uptimeElements[2]) * 60
    uptimeSeconds += int(uptimeElements[1]) * 3600
    uptimeSeconds += int(uptimeElements[0]) * 86400
    report['uptimeseconds'] = str(uptimeSeconds)

    # Get the main page with its various stats
    page = urllib.request.urlopen(modemStatusURL).read()
    page = page.decode("utf-8") # convert bytes to str
    page = page.replace('\x0D', '') # strip out the unwanted newlines within the text
    soup = BeautifulSoup(str(page), 'html.parser') # this call takes a lot of time

    # Before parsing all the numbers, be sure WAN is connected, else do not report
    internetStatus = soup.find('td', string="DOCSIS Network Access Enabled").next_sibling.get_text()
    if 'Allowed' not in internetStatus:
        return 1

    # Gather the various data items...
    block = soup.find('th', string="Downstream Bonded Channels").parent
    block = block.next_sibling # skip the header rows
    block = block.next_sibling
    report['downsnr'] = {}
    report['downpower'] = {}
    report['uppower'] = {}
    report['corrected'] = {}
    report['uncorrectable'] = {}
    report['corrected-count'] = {}
    report['uncorrectable-count'] = {}
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:
                newRow.append(re.sub("[^0-9.]", "", column.get_text()))
            report['downpower'][newRow[0]] = newRow[5]
            report['downsnr'][newRow[0]] = newRow[6]
            report['corrected-count'][newRow[0]] = newRow[7]
            report['uncorrectable-count'][newRow[0]] = newRow[8]
            if( numberOfMinutesElapsed > 1 ):
                report['corrected'][newRow[0]] = str( (float(newRow[7]) - float(priorReport['corrected-count'][newRow[0]])) / numberOfMinutesElapsed )
                if float(report['corrected'][newRow[0]]) < 0: # in case the modem was restarted, counts got reset
                    report['corrected'][newRow[0]] = '0'
            if( numberOfMinutesElapsed > 1 ):
                report['uncorrectable'][newRow[0]] = str( (float(newRow[8]) - float(priorReport['uncorrectable-count'][newRow[0]])) / numberOfMinutesElapsed )
                if float(report['uncorrectable'][newRow[0]]) < 0: # in case the modem was restarted, counts got reset
                    report['uncorrectable'][newRow[0]] = '0'

    block = soup.find('th', string="Upstream Bonded Channels").parent
    block = block.next_sibling # skip the header rows
    block = block.next_sibling
    for row in block.next_siblings:
        if isinstance(row, type(block)):
            newRow = []
            for column in row:
                newRow.append(re.sub("[^0-9.]", "", column.get_text()))
            report['uppower'][newRow[0]] = newRow[6]

    return 0

def reportConfig(args):
    openInput(jsonFile) # nearly every call type below relies on the list of channels, which are determined by scrape

    if any('downpower' in word for word in args):
        print(textwrap.dedent("""\
        graph_title [3] WAN Downstream Signal Strength
        graph_category x-wan
        graph_vlabel dB
        graph_args --alt-autoscale --lower-limit 0
        """))
        # graph_args --alt-autoscale-max --upper-limit 10 --lower-limit 0 --rigid
        # graph_scale no
        for chan in report['downpower']:
            print('down-power-ch'+chan+'.label', 'ch'+chan)
        return

    if any('downsnr' in word for word in args):
        print(textwrap.dedent("""\
        graph_title [4] WAN Downstream Signal SNR
        graph_category x-wan
        graph_vlabel dB
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['downsnr']:
            print('down-snr-ch'+chan+'.label', 'ch'+chan)
        return

    if any('corrected' in word for word in args):
        print(textwrap.dedent("""\
        graph_title [6] WAN Downstream Corrected
        graph_category x-wan
        graph_vlabel Blocks per Minute
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['corrected']:
            print('down-corrected-ch'+chan+'.label', 'ch'+chan)
        return

    if any('uncorrectable' in word for word in args):
        print(textwrap.dedent("""\
        graph_title [7] WAN Downstream Uncorrectable
        graph_category x-wan
        graph_vlabel Blocks per Minute
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale  --upper-limit 50 --lower-limit 30 --rigid
        # graph_scale no
        for chan in report['uncorrectable']:
            print('down-uncorrectable-ch'+chan+'.label', 'ch'+chan)
        return

    if any('uppower' in word for word in args):
        print(textwrap.dedent("""\
        graph_title [5] WAN Upstream Signal
        graph_category x-wan
        graph_vlabel dB
        graph_args --alt-autoscale
        """))
        # graph_args --alt-autoscale --upper-limit 50 --lower-limit 30 --rigid
        for chan in report['uppower']:
            print('up-power-ch'+chan+'.label', 'ch'+chan)
        return

    if any('ping' in word for word in args):
        print(textwrap.dedent("""\
        graph_title [2] WAN Next-Hop latency
        graph_vlabel millliSeconds
        graph_category x-wan
        graph_args --alt-autoscale --upper-limit 100 --lower-limit 0 --rigid --allow-shrink
        latency.label Next-Hop
        latency.colour cc2900
        """))
        return

    if any('speedtest' in word for word in args):
        print(textwrap.dedent("""\
        graph_category x-wan
        graph_title [1] WAN Speedtest
        graph_args --base 1000 --lower-limit 0 --upper-limit 35 --rigid --slope-mode
        graph_vlabel Megabits/Second
        graph_scale no
        distance.label V-Distance
        distance.type GAUGE
        distance.draw LINE
        distance.colour aaaaaa
        down.label Download
        down.type GAUGE
        down.draw LINE
        down.colour 0066cc
        up.label Upload
        up.type GAUGE
        up.draw LINE
        up.colour 44aa99
        graph_info Graph of Internet Connection Speed
        """))
        return
    # here if we were not called by one of the selectors above, so we do nothing

def getGateway(): #returns success by setting report['gateway']
    cmd = "/usr/sbin/traceroute -n --sendwait=0.5 --sim-queries=1 --wait=1 --queries=1 --max-hops="+str(target_hops)+" "+target_host
    output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    result = '0'
    for line in output.split('\n'):
        if line.startswith(' '+str(target_hops)+' '):
            result = line.split(' ')
            if len(result) > 3:
                result = result[3]
            break
    report['gateway'] = str( result )

def nextHopLatency():
    cmd = "/bin/ping -W 3 -nqc 3 " + report['gateway'] + " 2>/dev/null"
    try:
        output = subprocess.check_output(cmd, shell=True).decode("utf-8")
    except subprocess.CalledProcessError as e:
        report['next_hop_latency'] = 'NaN'
        return
    result = '0'
    for line in output.split('\n'):
        if line.startswith('rtt'):
            result = line.split('/')
            if len(result) > 4:
                result = result[4]
            break
    report['next_hop_latency'] = str( result )

    try: # clip this value at 100 to spare graph messes when something's wrong
        if float(result) > 100.0:
            result = str(100.0)
    except:
            result = '0'
    return result

def reportDateTime():
    # utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    # utc_offset = datetime.timedelta(seconds=-utc_offset_sec)
    # report['datetime'] = datetime.datetime.now().replace(tzinfo=datetime.timezone(offset=utc_offset),microsecond=0).isoformat()
    report['datetime_utc'] = datetime.datetime.utcnow().isoformat()

# def getfloat(astr):
#     return str(float( re.findall(r"[-+]?\d*\.\d+|\d+", astr )[0]))

def openInput(jsonFile):
    global report, priorReport
    try:
        fhInput = open(jsonFile, 'r')
        report = json.load(fhInput)
        fhInput.close()
    except (FileNotFoundError, OSError) as e:
        print("something went wrong opening for read", jsonFile)
        print("that error was:", e)
        sys.exit()

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
