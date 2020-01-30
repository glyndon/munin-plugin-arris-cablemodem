#!/usr/bin/env python3

import os
import datetime
import json
import subprocess

LATENCY_GATEWAY_HOPS = 3
LATENCY_GATEWAY_HOST = '8.8.4.4'
LATENCY_GATEWAY_CMD = "/usr/sbin/traceroute -n --sim-queries=1 --wait=1 --queries=1 --max-hops="
LATENCY_MEASURE_CMD = "/bin/ping -W 3 -nqc 3 "

report = {}

def main(args):
    global report
    # issue the command to discover the gateway at the designated hop distance
    cmd = LATENCY_GATEWAY_CMD \
        + str(LATENCY_GATEWAY_HOPS) \
        + " " \
        + LATENCY_GATEWAY_HOST
    try:
        output = result = subprocess.run(cmd.split(' '), capture_output=True)
    except subprocess.CalledProcessError:
        pass
    # parse the results for the IP addr of that hop
    result = '0'
    for line in output.stdout.decode("utf-8").split('\n'):
        if line.startswith(' ' + str(LATENCY_GATEWAY_HOPS) + ' '):
            result = line.split(' ')
            if len(result) > 3:
                result = result[3]
            break
    report['gateway'] = str(result)
    # issue the command to measure latency to that hop
    cmd = LATENCY_MEASURE_CMD + report['gateway'] # + " 2>/dev/null"
    try:
        output = result = subprocess.run(cmd.split(' '), capture_output=True)
    except subprocess.CalledProcessError:
        pass
    # parse the results for the 4th field which is the average delay
    result = '0'
    for line in output.stdout.decode("utf-8").split('\n'):
        print(line)
        if line.startswith('rtt'):
            fields = line.split('/')
            if len(fields) > 4:
                result = fields[4]
            break
    # clip this value to spare graph messes when something's wrong
    try:
        if float(result) > 30.0:
            result = str(30.0)
    except ValueError:
        result = '0'
    report['next_hop_latency'] = str(result)





    print(json.dumps(report,indent=2))




# def runSpeedTest(output_json_file):

#     CMD = ["/usr/bin/speedtest-cli"]
#     CMD.append("--json")

#     # ===== Inclusions below ======
#     # CMD = CMD + ["--server", "14162"]) # ND's server
#     # CMD = CMD + ["--server", "5025"]) # ATT's Cicero, Il server
#     # CMD = CMD + ["--server", "5114"]) # ATT's Detroit server
#     # CMD = CMD + ["--server", "5115"]) # ATT's Indianapolis server
#     # CMD = CMD + ["--server", "1776"]) # Comcast's Chicago server

#     # ===== Exclusions below ======
#     # CMD = CMD + ["--exclude", "16770") # Fourway.net server; its upload speed varies weirdly
#     # CMD = CMD + ["--exclude", "14162"] # ND's server

#     outFile = open(output_json_file, 'w')
#     result = subprocess.run(CMD, stdout=outFile)
#     outFile.close()
#     # print(result.returncode)
#     return result.returncode == 0  # return a boolean

#     currentTime = datetime.datetime.utcnow()

#     fhInput = open('./speedtest.json', 'r')
#     report = json.load(fhInput)
#     fhInput.close()

#     print('first pass...')
#     # print(json.dumps(report,indent=2,sort_keys=True))

#     print('\n   UTC:', currentTime)
#     print('  last:', report['timestamp'][:-1])

#     priorTime = datetime.datetime.fromisoformat(report['timestamp'][:-1])
#     print('parsed:', priorTime)
#     # c = currentTime-priorTime
#     print('  diff:', (currentTime-priorTime).total_seconds() / 60)


    # global thing

    # print('in main...')

    # try:
    #     thing = 'no key, this is default'
    #     thing = os.environ['MUNIN_PLUGSTATE']
    #     # thing = os.environ['PATH']
    # except KeyError:
    #     # print('exception occurred:', e)
    #     # thing = 'no key found'
    #     pass
    # print('MUNIN_PLUGSTATE: ', thing)

#     # thing(dicta)
#     # print( 'nothing:', dicta)
#     triggers = ['config','wan-up','down']
#     plugin_nouns = ['config', 'wan-downpower', 'wan-downsnr', 'wan-uppower', 'wan-corrected', 'wan-uncorrectable', 'wan-ping', 'wan-speedtest']

#     # print('any:', any(triggers in x for x in args))
#     # for word in args:
#     #     print('in:',word in triggers)
#     print('args:',list(arg for arg in args))
#     print('nouns:',list(noun for noun in plugin_nouns))
#     print()

#     # print(any(noun in arg for arg in args for noun in plugin_nouns))
#     if any(noun in arg for arg in args for noun in plugin_nouns):
#         print('any: positive trigger')

#     for noun in plugin_nouns:
#         for arg in args:
#             # print('noun:',noun,'arg:',arg)
#             if noun in arg:
#                 print('nest: positive trigger')

#     return

#     if any(t in word for word in args for t in triggers):
#         print('positive trigger')

#     for t in triggers:
#         if any(t in word for word in args):
#             print('hit')

# def thing(d):
#     # d = {'snow': "cold", 'heat':"welcome"}
#     # print( 'thing:', dicta)

#     # # any(x in a for x in b)
#     # # if any(hit in triggers for hit in args):
#     # # print ('args:',args)
#     # # print('x in triggers', list(x for x in triggers))
#     # # print('x in args', list(x for x in args))
#     # if './test.py' in args:
#     #     print('up hit')
#     # print(len(args)==1)
#     pass

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))