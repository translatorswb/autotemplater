import time
import copy
import string
import json
import requests, uuid, json

SENTENDPUNCS = ['.', '?', '!']
MAX_CHARS_PER_SUBSEG = 80
SUB_END_BUFFER = 0.5

def get_azure_translator(src, trg, subscription_key, endpoint = "https://api.cognitive.microsofttranslator.com", location = "westeurope"):
    path = '/translate'
    constructed_url = endpoint + path

    if '-' in src:
        src = src.split('-')[0]

    if '-' in trg:
        trg = trg.split('-')[0]

    params = {
        'api-version': '3.0',
        'from': src,
        'to': trg
    }

    headers = {
        'Ocp-Apim-Subscription-Key': subscription_key,
        'Ocp-Apim-Subscription-Region': location,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }

    # request = requests.post(constructed_url, params=params, headers=headers, json=body)
    # response = request.json()

    def translate(string):
        request = requests.post(constructed_url, params=params, headers=headers, json=[{'text': string}])
        response = request.json()
        if request.status_code == 200:
            return response[0]['translations'][0]['text']
        else:
            print("Cannot establish connection to translator")
            print(response)
            return '~'+string+'~'

    return lambda x: translate(x)

def sec_to_srt_timestamp(sec) -> str:
    """Convert seconds to hh:mm:ss timestamp format"""
    ty_res = time.gmtime(sec)
    time_in_ms = sec * 1000
    res = time.strftime("%H:%M:%S", ty_res) + ",%03.0f"%(time_in_ms%1000)
    return res


def speaker_turns_to_srt(speaker_turns, output_path, write_speaker_id=False, txttag='rawtxt'):
    """Creates an SRT subtitle from speaker turn list"""

    out_text = ""
    for i, t in enumerate(speaker_turns):
        if not t.get(txttag):
            continue 
                
        start_time = t['start']
                
        #subtitles can stay on the screen longer than the actual end timestamp
        next_t = None
        if i+1 < len(speaker_turns):
            next_t = speaker_turns[i+1]

        if next_t and t['end'] + SUB_END_BUFFER < next_t['start']:
            end_time = t['end'] + SUB_END_BUFFER
        elif next_t:
            #end_time = next_t['start']
            end_time = t['end']
        else:
            end_time = t['end'] + SUB_END_BUFFER

        out_text += str(i+1) + '\n'
        out_text += sec_to_srt_timestamp(start_time) + ' --> ' + sec_to_srt_timestamp(end_time) + '\n'
        
        if write_speaker_id:# and 'speaker' in t:
            out_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        
        out_text += t[txttag]
        out_text += '\n\n'
            
    with open(output_path, 'w', encoding='utf8') as f:
        f.write(out_text)

def get_sentend_pos(string):
    return [pos for pos, word in enumerate(string.split()) if word[-1] in SENTENDPUNCS]

def fix_word_offsets(wt, fix_by_sec):
    fixed = copy.deepcopy(wt)
    for w in fixed:
        newval = int(w['Offset'] - fix_by_sec * 10000000)
        w['Offset'] = newval
    return fixed

def optimal_split_text(text, max_char):
    split_segments = []
    current_segment = ""
    tokens = text.split()
    for w in tokens:
        if w[-1] in string.punctuation and len(current_segment + " " + w) > max_char*0.7:
            current_segment += w
            split_segments.append(current_segment)
            current_segment = ""
        elif len(current_segment + " " + w) < max_char:
            current_segment += w + " "
            continue
        else:
            split_segments.append(current_segment[:-1])
            current_segment = w + " "
    if current_segment:
        split_segments.append(current_segment)
    return split_segments

def split_long_turn(turn, texttag, max_chars=MAX_CHARS_PER_SUBSEG, debug=False):
    newturns = []
    if debug: print("split_long_turn:", texttag, turn[texttag])
    text_segments = optimal_split_text(turn[texttag], max_chars)
    if debug: print("split_long_turn:text_segments", text_segments)
    fullcharlen=len(turn[texttag])
    start = turn['start']
    at_token = 0
    for seg in text_segments:
        if debug: print(">>", seg)
        no_tokens = len(seg.split())
        segcharlen = len(seg)
        duration = turn['end'] - turn['start']
        ratio = segcharlen / fullcharlen

        respective_duration = duration * segcharlen / fullcharlen
        end = start + respective_duration
        end_token = at_token+no_tokens

    #     fix_by_sec = 0 #TODO if necessary
    #     wordtiming = fix_word_offsets(turn['wordtiming'][at_token:end_token], fix_by_sec)

        splitturn = {'start': start, 
                     'end': start + respective_duration, 
                     'speaker': turn['speaker']}
        
        splitturn[texttag] = seg
        
        if debug: print(">>", splitturn['start'], splitturn['end'])

        start = end
        at_token = end_token

        newturns.append(splitturn)
    return newturns

def segment_turns(turns, max_chars=MAX_CHARS_PER_SUBSEG, translator_func=None, debug=False):
    sentturns = []
    sentturns_translated = []
    for turn in turns:
        turnstart = turn['start']
        if debug: print(">>>", turnstart)
        if debug: print(turn['puncdtext'])
        sentends = get_sentend_pos(turn['puncdtext'])
        if debug: print(sentends)
        prevsentendindex = 0
        for sentendindex in sentends:
            if debug: print("from", prevsentendindex, "to", sentendindex)
            puncdtext = ' '.join(turn['puncdtext'].split()[prevsentendindex:sentendindex+1])
            rawtext = ' '.join(turn['rawtext'].split()[prevsentendindex:sentendindex+1])
            
            sentstart = turnstart + turn['wordtiming'][prevsentendindex]['Offset']/10000000
            sentend = turnstart + turn['wordtiming'][sentendindex]['Offset']/10000000 + turn['wordtiming'][sentendindex]['Duration']/10000000
            
            fix_by_sec = sentstart - turnstart
            wordtiming = fix_word_offsets(turn['wordtiming'][prevsentendindex:sentendindex+1], fix_by_sec)
            #wordtiming = turn['wordtiming'][prevsentendindex:sentendindex+1]
            
            sentturn = {'start': sentstart, 
                 'end': sentend, 
                 'speaker': turn['speaker'], 
                 'toolong':None, 
                 'rawtext': rawtext, 
                 'puncdtext': puncdtext,
                 'wordtiming': wordtiming } 
            
            if debug: print(sentturn['start'], sentturn['end'])
            if debug: print(sentturn['puncdtext'])
            
            if translator_func:
                translated = translator_func(puncdtext)

                sentturn['translated'] = translated
                if debug: print(sentturn['translated'])

                sentturns_translated.extend(split_long_turn(sentturn, 'translated', max_chars, debug))
                
            sentturns.extend(split_long_turn(sentturn, 'puncdtext', max_chars))
                
            prevsentendindex = sentendindex+1
            if debug: print()
    return sentturns, sentturns_translated
