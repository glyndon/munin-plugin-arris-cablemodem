#!/usr/bin/env python3

from bs4 import BeautifulSoup
import requests
import datetime

def main(args):

    print('pre-read')
    # fh = open('sb8200/status.html','r') # or use mode 'rb' and then b'char' in replace function below 
    # # fh = open('mystatus.html','r') # or use mode 'rb' and then b'char' in replace function below 
    # page = fh.read()
    # fh.close()
    page = requests.get('http://192.168.100.1/RgSwInfo.asp', timeout=25).text
    # page = requests.get('http://192.168.100.1/', timeout=25).text


    print(type(page),file=sys.stderr)

    page = page.translate(str.maketrans('','',"\n\x00\x09\r"))

    # page = requests.get(MODEM_STATUS_URL, timeout=25).text
    soup = BeautifulSoup(str(page), 'html.parser')
    # soup = BeautifulSoup(str(page), 'html5lib')
    # print(soup)

    print(soup.original_encoding)
    model_name = soup.find(id='thisModelNumberIs')
    if not model_name:
        model_name = 'Cablemodem'
    else:
        print(model_name.get_text())
        print(model_name)
        print(model_name.parent())
        return



    # td = soup.find('td', string="DOCSIS Network Access Enabled")
    # if not td:
    #     print("tag not found")
    #     return False
    # else:
    #     print('tabledata', td)
    #     print('parent', td.parent())
    #     print('parent+1', td.parent()[1])
    #     print('next_sib', td.next_sibling)
    #     print('next_sibx2', td.next_sibling.next_sibling)
    #     # print(td.parent()[1].get_text())
    #     # print(td.next_sibling.get_text())
    # # sys.exit(0)


    # internetStatus = td.parent()[1].get_text()
    # if 'Allowed' not in internetStatus:
    #     print("# Modem indicates no Internet Connection as of (local time):",
    #           datetime.datetime.now().isoformat(), file=sys.stderr)
    #     return False
    # else:
    #     print('happy')

# import html.parser
# import os
# import datetime
# import json
# import subprocess

# class ArrisHTMLParser(html.parser.HTMLParser):
#     state = None
#     row = 0
#     col = 0
#     table_type = None
#     result_model = None
#     result_downstream = []
#     result_upstream = []

#     def handle_starttag(self, tag, attrs):
#         for key, value in attrs:
#             if key == 'id' and value == 'thisModelNumberIs':
#                 self.state = 'model'
#         if tag == 'table':
#             self.state = 'table'
#             self.table_type = None
#             self.row = 0
#             self.col = 0
#         if tag == 'tr':
#             self.row = self.row + 1
#             self.col = 0
#         if tag == 'td':
#             self.col = self.col + 1

#     def handle_endtag(self, tag):
#         if tag == 'table' and self.state == 'table':
#             self.state = None

#     def handle_data(self, data):
#         data = data.strip()
#         if data:
#             print(data)
#             # if self.state == 'model':
#             #     self.result_model = data
#             #     self.state = None

# def main(args):

#     page = open('modem2.html','r')

#     parser = ArrisHTMLParser()
#     parser.feed(page.read()) # .decode('utf-8')



    # f = open('statefile')
    # report = json.load(f)
    # f.close()
    # print(type(report))
    # for key in sorted(report['downstream_channels']):
    #     print("downsnr{0}.label Channel {1}".format(key, report['downstream_channels'][key]['channel_id']))
    #     print('id', report['downstream_channels'][key]['channel_id'], key)

    # print(json.dumps(report, indent=2))


    # da = {'one': '1', 'two': '2', 'three': '3'}
    # db = {'four': '4', 'five': '5', 'six': '6'}

    # db['extra'] = 'socks'
    # db['also'] = da

    # print(json.dumps(db,indent=2))

    # fh = open('mystatus.html','r') # or use mode 'rb' and then b'char' in replace function below 
    # page = fh.read()
    # fh.close()
    # # page = page.replace('\n', '')  # strip unwanted newlines
    # page = page.replace('\x00', '')  # strip unwanted linefeeds
    
    # print(page)
    # soup = BeautifulSoup(str(page), 'html5lib')
    # print(soup.prettify())
    # return False



    # # issue the command to discover the gateway at the designated hop distance
    # cmd = LATENCY_GATEWAY_CMD \
    #     + str(LATENCY_GATEWAY_HOPS) \
    #     + " " \
    #     + LATENCY_GATEWAY_HOST
    # try:
    #     output = result = subprocess.run(cmd.split(' '), capture_output=True)
    # except subprocess.CalledProcessError:
    #     pass
    # # parse the results for the IP addr of that hop
    # result = '0'
    # for line in output.stdout.decode("utf-8").split('\n'):
    #     if line.startswith(' ' + str(LATENCY_GATEWAY_HOPS) + ' '):
    #         result = line.split(' ')
    #         if len(result) > 3:
    #             result = result[3]
    #         break
    # report['gateway'] = str(result)
    # # issue the command to measure latency to that hop
    # cmd = LATENCY_MEASURE_CMD + report['gateway'] # + " 2>/dev/null"
    # try:
    #     output = result = subprocess.run(cmd.split(' '), capture_output=True)
    # except subprocess.CalledProcessError:
    #     pass
    # # parse the results for the 4th field which is the average delay
    # result = '0'
    # for line in output.stdout.decode("utf-8").split('\n'):
    #     print(line)
    #     if line.startswith('rtt'):
    #         fields = line.split('/')
    #         if len(fields) > 4:
    #             result = fields[4]
    #         break
    # # clip this value to spare graph messes when something's wrong
    # try:
    #     if float(result) > 30.0:
    #         result = str(30.0)
    # except ValueError:
    #     result = '0'
    # report['next_hop_latency'] = str(result)



    # print(json.dumps(report,indent=2))



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
    pass

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))