# Create automatically diarized and transcribed oTranscribe template using pyannote and ASR API or Azure 

import argparse
import sys
import time
import os
import wave
import json
import subprocess
import tempfile
import shutil
import random
import requests
import validators
from pydub import AudioSegment
from tqdm import tqdm

API_TRANSCRIBE_URL = "http://127.0.0.1:8010/transcribe"  #default running on local
API_TRANSCRIBE_URL_ENDPOINT = "short"
ASR_API_FLAG = 'api'
AZURE_ASR_FLAG = 'azure'
DEFAULT_AZURE_REGION = 'westeurope'
REVISION_PATH = "revision"
DOWNLOAD_PATH = "download"
SPEAKER_DELIMITER = ':'
SUPPORTED_ASR_SERVICE_TAGS = [ASR_API_FLAG, AZURE_ASR_FLAG]

SAMPLE_COUNT = 5
DEFAULT_MAX_TURN_LENGTH = 30.0 #(seconds) used only with speaker-based turns
SEGMENT_AT_PAUSE_LENGTH = 3.0 #(seconds) used only with speaker-based turns
SUB_END_BUFFER = 0.5 #seconds to wait for subtitle entry to pass

USE_AZURE_SDK = True #if false, it'll use requests library (works but sometimes unstable)
DUMMY_TRANSCRIPTION = False  #Emulates transcription for debugging

parser = argparse.ArgumentParser(description="oTranscribe template maker")
parser.add_argument('-i', '--audio', type=str, required=True, help='Input audio path or URL')
parser.add_argument('-l', '--lang', type=str, help='Transcription language')
parser.add_argument('-o', '--out', type=str, help='Output directory (default: input audio directory)')
parser.add_argument('-p', '--punctoken', type=str, help='PunkProse token if sending to remote API (Not implemented)') #TODO
parser.add_argument('-a', '--azuretoken', type=str, help='Azure token if sending to Azure ASR')
parser.add_argument('-r', '--azureregion', type=str, help='Azure region if sending to Azure ASR (default: %s)'%DEFAULT_AZURE_REGION, default=DEFAULT_AZURE_REGION)
parser.add_argument('-x', '--transcribe', type=str, help='Automatic transcription service %s'%(SUPPORTED_ASR_SERVICE_TAGS))
parser.add_argument('-u', '--apiurl', type=str, help='ASR-API URL endpoint (default: http://127.0.0.1:8010/transcribe/short)', default=API_TRANSCRIBE_URL)
parser.add_argument('-t', '--turn', type=str, help='Turn on speaker or speech segment (default: segment)', default='segment')
parser.add_argument('-s', '--sid', action='store_true', help='Write speaker id on turns (default: False)')
parser.add_argument('-v', '--skiprevision', action='store_true', help='Skip revision query (default: False)')
parser.add_argument('-m', '--maxturnlen', type=float, help='Maximum turn length when turns are on speaker changes (default: 30 seconds)', default=DEFAULT_MAX_TURN_LENGTH)

def sec_to_timestamp(sec) -> str:
    """Convert seconds to hh:mm:ss timestamp format"""
    ty_res = time.gmtime(sec)
    res = time.strftime("%H:%M:%S",ty_res)
    return res

def sec_to_srt_timestamp(sec) -> str:
    """Convert seconds to hh:mm:ss timestamp format"""
    ty_res = time.gmtime(sec)
    time_in_ms = sec * 1000
    res = time.strftime("%H:%M:%S", ty_res) + ",%03.0f"%(time_in_ms%1000)
    return res

def timestamp_spanner(sec) -> str:
    """Creates an XML line for timestamp from seconds in audio"""
    ty_res = time.gmtime(sec)
    res = sec_to_timestamp(sec)
    span_str = '<span class="timestamp" data-timestamp="%s">%s</span>'%(sec, res)
    return span_str

def get_speaker_turns(diarization_output, turn_on_segment, max_turn_length = DEFAULT_MAX_TURN_LENGTH, segment_at_pause_length = SEGMENT_AT_PAUSE_LENGTH):
    """Makes a minimal speaker turn list from diarization output. Merges segments that belong to same speaker"""

    speaker_turns = []
    current_turn = {'speaker':None, 'start':0.0, 'end':0.0}
    for i, s in enumerate(diarization_output):
        speaker_change = not s['label'] == current_turn['speaker']
        current_turn_length = current_turn['end'] - current_turn['start']
        pause_from_last_segment = s['segment']['start'] - current_turn['end']
        
        #calculate total length with the upcoming segment
        length_with_next_segment = 0.0
        if i + 1 < len(diarization_output):
            length_with_next_segment = diarization_output[i+1]['segment']['end'] - current_turn['start']

        if turn_on_segment or speaker_change or length_with_next_segment > max_turn_length or pause_from_last_segment >= segment_at_pause_length:
            #close current turn (unless it's the first turn)
            if current_turn['speaker']:
                speaker_turns.append(current_turn)
                if current_turn_length > max_turn_length:
                    current_turn['toolong'] = True

            #start new turn
            current_turn = {'start':s['segment']['start'], 'end':s['segment']['end'],
                            'speaker':s['label'], 'toolong': False}
        else:
            current_turn['end'] = s['segment']['end']

    #Grab that last remaining segment
    if current_turn:
        current_turn['end'] = s['segment']['end']
        speaker_turns.append(current_turn)
        if current_turn_length > max_turn_length:
            current_turn['toolong'] = True
            
    return speaker_turns



def speaker_turns_to_otr(speaker_turns, output_path, write_speaker_id=False):
    """Creates an OTR template from speaker turn list"""

    otr_text = ""
    for t in speaker_turns:
        if 'rawtext' in t or 'puncdtext' in t:
            if not t['puncdtext'] and not t['rawtext']:
                continue 

        otr_text += timestamp_spanner(t['start']) + ' '
        
        if write_speaker_id: #and 'speaker' in t:
            otr_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'puncdtext' in t and t['puncdtext']:
            otr_text += t['puncdtext']
        elif 'rawtext' in t and t['rawtext']:
            otr_text += t['rawtext']
        otr_text += '<br /><br />'
        
    otr_format_dict = {'text': otr_text, "media": "", "media-time":"0.0"}
    
    with open(output_path, 'w') as f:
        f.write(json.dumps(otr_format_dict))

def speaker_turns_to_txt(speaker_turns, output_path, write_speaker_id=False):
    """Creates an TXT file from speaker turn list"""

    out_text = ""
    for t in speaker_turns:
        if 'rawtext' in t or 'puncdtext' in t:
            if not t['puncdtext'] and not t['rawtext']:
                continue  
            
        out_text += sec_to_timestamp(t['start']) + ' '
        
        if write_speaker_id:# and 'speaker' in t:
            out_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'puncdtext' in t and t['puncdtext']:
            out_text += t['puncdtext']
        elif 'rawtext' in t and t['rawtext']:
            out_text += t['rawtext']
        out_text += '\n'
            
    with open(output_path, 'w') as f:
        f.write(out_text)

def speaker_turns_to_srt(speaker_turns, output_path, write_speaker_id=False):
    """Creates an SRT subtitle from speaker turn list"""

    out_text = ""
    for i, t in enumerate(speaker_turns):
        if 'rawtext' in t:
            if not t['rawtext']:
                continue 
            
        #subtitles can stay on the screen longer than the actual end timestamp
        next_t = None
        if i+1 < len(speaker_turns):
            next_t = speaker_turns[i+1]

        if next_t and t['end'] + SUB_END_BUFFER < next_t['start']:
            end_timestamp = t['end'] + SUB_END_BUFFER
        elif next_t:
            end_timestamp = next_t['start']
        else:
            end_timestamp = t['end'] + SUB_END_BUFFER

        out_text += str(i) + '\n'
        out_text += sec_to_srt_timestamp(t['start']) + ' --> ' + sec_to_srt_timestamp(end_timestamp) + '\n'
        
        if write_speaker_id:# and 'speaker' in t:
            out_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'rawtext' in t:
            out_text += t['rawtext']
        out_text += '\n\n'
            
    with open(output_path, 'w') as f:
        f.write(out_text)

def print_speakers_data(diarization_dict):
    """Prints number of speakers and number of segments for each of them on the screen"""

    speakers_info = {}
    for s in diarization_dict['content']:
        if s['label'] not in speakers_info:
            speakers_info[s['label']] = 1
        else:
            speakers_info[s['label']] += 1
    print("%i speakers detected"%len(speakers_info), end=", ")
    for s in speakers_info:
        print("%s: %i segments"%(s, speakers_info[s]), end=' ')
    print()

def do_diarization(wav_path):
    """Performs pyannote diarization on wav file and outputs its results"""

    from pyannote.core import Annotation, Segment
    from pyannote.audio.features import RawAudio
    import torch

    file = {'audio': wav_path}
    pipeline = torch.hub.load('pyannote/pyannote-audio', 'dia')
    diarization = pipeline(file)
    diarization_dict = diarization.for_json()

    return diarization_dict

def audio_convert(audio_path):
    """Converts audio to mono wav (unless it's already or there's a converted version in the same directory)"""

    do_convert = False
    if os.path.splitext(audio_path)[1][1:] == 'wav':
        wav_path = audio_path
        try:
            wf = wave.open(wav_path, "rb")
            framerate = wf.getframerate()

            if wf.getnchannels() != 1:
                do_convert = True
        except:
            do_convert = True
    else:
        wav_path = os.path.join(os.path.dirname(audio_path), os.path.splitext(os.path.basename(audio_path))[0] + '.wav')
        if os.path.exists(wav_path):
            return audio_convert(wav_path)
        else:
            do_convert = True

    if do_convert:
        print("Converting audio to wav", wav_path)
        process = subprocess.call(['ffmpeg', '-loglevel', 'quiet', '-i',
                                        audio_path, '-ac', '1', wav_path])

        return wav_path
    else:
        print("Reading wav file", audio_path)

        return audio_path


def initialize_azure_config_sdk(subscription_id, lang_code, region):
    """Returns speech_config to run azure ASR using Azure speech SDK"""
    global speechsdk
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(subscription=subscription_id, region=region)
    speech_config.speech_recognition_language=lang_code
    speech_config.request_word_level_timestamps() 

    #TODO: Make sure lang_code is supported
    return speech_config

def transcribe_with_azure_sdk(audio_path, speech_config):
    """Does recognition with Azure on give audio using Azure speech SDK"""
    audio_input = speechsdk.AudioConfig(filename=audio_path)
    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_input)

    result = speech_recognizer.recognize_once_async().get()

    response_json = json.loads(result.json) 

    try:
        raw_transcript = response_json['NBest'][0]['ITN']
        punctuated_transcript = response_json['NBest'][0]['Display']
        word_timing = response_json["NBest"][0]['Words']
    except:
        raw_transcript = ''
        punctuated_transcript = ''
        word_timing = []

    return raw_transcript, punctuated_transcript, word_timing

def initialize_azure_config_requests(subscription_id, lang_code, region):
    """Generates necessary info to do Azure Speech ASR using requests"""

    url = "https://" + region + ".stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1?language=" + lang_code + "&format=detailed"
    fetch_token_url = 'https://westeurope.api.cognitive.microsoft.com/sts/v1.0/issueToken'
    headers = {
        'Ocp-Apim-Subscription-Key': subscription_id
    }
    response = requests.post(fetch_token_url, headers=headers)

    token  = str(response.text)
    headers = {
          'Authorization': f'Bearer {token}',
          'Content-Type': 'audio/wave',
          'Accept': 'application/json'
        }

    #TODO: Make sure lang_code is supported
    #TODO: Get word alignment info

    return {'token':token, 'url':url, 'headers':headers}

def transcribe_with_azure_requests(audio_path, speech_config):
    """Sends a Azure API recognition request for audio and returns its transcript"""
    raw_transcript = ''
    punctuated_transcript = ''
    with open(audio_path,"rb") as payload:
        response = requests.request("POST", speech_config['url'], headers=speech_config['headers'], data=payload)

        if response.status_code == 200:
            response_json = response.json()
            try:
                raw_transcript = response_json['NBest'][0]['ITN']
                punctuated_transcript = response_json['NBest'][0]['Display']
                #TODO: Get word alignment info
            except:
                pass
        else:
            print("Error processing", audio_path)
            print(response.text.encode('utf8'))

    return raw_transcript, punctuated_transcript, [] #TODO: word timing info

def initialize_api_config(lang, api_url, scorer='default'):
    """Generates necessary info to do ASR with TWB-API"""
    all_good = False
    try:
        response = requests.request("GET", api_url, headers={})

        if lang in response.json()['languages']:
            all_good = True
        else:
            print("ERROR: Language %s not supported by ASR API"%lang)
    except Exception as e:
        print("ERROR: Cannot establish connection with ASR API")
        print(e)

    if not all_good:
        return None

    api_url_endpoint = api_url + '/' + API_TRANSCRIBE_URL_ENDPOINT
    return {'lang': lang, 'scorer':scorer, 'url': api_url_endpoint}

def transcribe_with_asr_api(audio_path, config):
    """Sends a ASR-API recognition request for audio and returns its transcript"""
    url_endpoint = config['url']
    payload={'lang': config['lang']} #TODO: doesn't get the scorer in. 
    headers = {}
    
    #Send to ASR API
    audio_filename = os.path.basename(audio_path)
    
    files=[('file',(audio_filename, open(audio_path,'rb'),'audio/wav'))]
    
    try:
        response = requests.request("POST", url_endpoint, headers=headers, data=payload, files=files)
    except Exception as e:
        print("ERROR: Cannot establish connection with ASR API")
        print(e)
        sys.exit()
    
    response_dict = response.json()

    if response.ok:
        transcript = response_dict["transcript"]
    else:
        print("Cannot read response for file", audio_filename)
        print(response_dict)
        transcript = ""
        
    return transcript, None, None #TODO: punctuated transcript and word timing info

def dummy_transcriber(path, config):
    return "Lorem ipsum dolor sit amet"

def get_transcription_of_chunk(complete_audio, start_sec, end_sec, chunk_path, transcriber_func, speech_config=None):
    """Transcribes an interval of audio with start and end seconds specified using ASR service"""

    start_ms = start_sec * 1000
    end_ms = end_sec * 1000
    
    audio_segment = complete_audio[start_ms:end_ms]
    
    audio_chunk_filename = "%.2f"%start_sec + "-" + "%.2f"%end_sec + ".wav"
    audio_chunk_path = os.path.join(chunk_path, audio_chunk_filename)
    
    audio_segment.export(audio_chunk_path, format="wav")
    
    raw_transcript, post_transcript, word_timing = transcriber_func(audio_chunk_path, speech_config)

    #print("%.2f-%.2f: %s"%(start_sec, end_sec, transcript))
    return raw_transcript, post_transcript, word_timing

def dump_chunk(audio, start_sec, end_sec, chunk_path):
    """Cuts and places a chunk of audio to path (for revision)"""

    start_ms = start_sec * 1000
    end_ms = end_sec * 1000

    audio_segment = audio[int(start_ms):int(end_ms)]
    
    audio_chunk_filename = "%.2f"%start_sec + "-" + "%.2f"%end_sec + ".wav"
    audio_chunk_path = os.path.join(chunk_path, audio_chunk_filename)
    
    audio_segment.export(audio_chunk_path, format="wav")
    
    return audio_chunk_path

def main():

    #Parse args
    args = parser.parse_args()

    audio_input = args.audio
    out_path = args.out
    lang = args.lang
    azure_token = args.azuretoken
    azure_region = args.azureregion
    asr_service = args.transcribe
    turn_on = args.turn
    write_speaker_id = args.sid
    asr_api_url_endpoint = args.apiurl
    skip_revision_query = args.skiprevision
    max_turn_length = args.maxturnlen

    #Input checks
    if not audio_input:
        print("ERROR: Specify input audio path or URL (-i)")
        sys.exit()

    if asr_service and not lang:
        print("ERROR: Specify audio language with -l")
        sys.exit()

    #Determine ASR procedure to use
    if asr_service:
        if asr_service==AZURE_ASR_FLAG:
            if asr_service==AZURE_ASR_FLAG and not azure_token:
                print("ERROR: Specify service token to use Azure transcription (-a)")
                sys.exit()

            if USE_AZURE_SDK:
                transcribe_func = transcribe_with_azure_sdk
                initialize_azure_config = initialize_azure_config_sdk
            else:
                transcribe_func = transcribe_with_azure_requests
                initialize_azure_config = initialize_azure_config_requests
        elif asr_service == ASR_API_FLAG:
            transcribe_func = transcribe_with_asr_api
        else:
            print("ERROR: ASR service %s not supported. Select from %s"%(asr_service, SUPPORTED_ASR_SERVICE_TAGS))
            sys.exit()

    elif DUMMY_TRANSCRIPTION:
        transcribe_func = dummy_transcriber

    if turn_on == 'segment':
        turn_on_segment = True
    elif turn_on == 'speaker':
        turn_on_segment = False
    else:
        print("ERROR: Unknown turn flag %s. It needs to be 'segment' or 'speaker'")
        sys.exit()

    #Initialize transcription service
    if asr_service == ASR_API_FLAG:
        speech_config = initialize_api_config(lang, asr_api_url_endpoint)
        if not speech_config:
            print("Couldn't initialize ASR API. Exiting.")
            sys.exit()
    elif asr_service == AZURE_ASR_FLAG:
        speech_config = initialize_azure_config(azure_token, lang, azure_region)
        if not speech_config:
            print("Couldn't initialize Azure ASR. Exiting.")
            sys.exit()
    elif DUMMY_TRANSCRIPTION:
        print("Dummy transcription for debugging")
        asr_service = True
        speech_config = None
    else:
        asr_service = None

    #Check if input is URL
    if validators.url(audio_input):
        #Open download directory
        if not os.path.exists(DOWNLOAD_PATH):
            os.makedirs(DOWNLOAD_PATH)

        audio_name = audio_input.split("/")[-1]
        audio_path = os.path.join(DOWNLOAD_PATH, audio_name)

        if not os.path.exists(audio_path):
            print("Downloading audio given by URL")
            #download audio
            try:
                response = requests.get(audio_input)
                open(audio_path, 'wb').write(response.content)
            except:
                print("ERROR: Couldn't download audio file given by URL")
                sys.exit()
            print("Audio downloaded to", audio_path)
        else:
            print("Using cached audio file", audio_path)
    else:
        audio_path = audio_input
        #Check audio file exists
        if not os.path.exists(audio_path):
            print("ERROR: File not found", audio_path)
            sys.exit()

    #Determine output path
    if not out_path:
        out_path = os.path.dirname(audio_path)
    else:
        if os.path.exists(out_path):
            if not os.path.isdir(out_path):
                print("ERROR: %s is a file"%out_path)
                sys.exit()
        else:
            os.mkdir(out_path)

    #Report on setup
    print("ASR Service:", asr_service)
    print("Output path:", out_path)
    print('Turn on segment:', turn_on_segment)
    print("Maximum turn length: %f s"%max_turn_length)
    print("Skip diarization revision:", skip_revision_query)

    #Output files 
    audio_id = os.path.splitext(os.path.basename(audio_path))[0]
    out_json_path = os.path.join(out_path ,audio_id + '-rawdiarization.json')
    out_empty_otr_path = os.path.join(out_path ,audio_id + '-diarization.otr')
    out_final_otr_path = os.path.join(out_path ,audio_id + '-autotemplate.otr')
    out_txt_path = os.path.join(out_path ,audio_id + '-transcript.txt')
    out_srt_path = os.path.join(out_path ,audio_id + '-subtitles.srt')
    out_mapped_json_path = os.path.join(out_path ,audio_id + '-reviseddiarization.json')
    out_mapping_path = os.path.join(out_path ,audio_id + '-spkrevisionmap.json')
    out_asr_path = os.path.join(out_path, audio_id + '-asr.json') 

    #Ensure wav format input
    wav_path = audio_convert(audio_path)

    #Read audio to memory
    complete_audio = AudioSegment.from_wav(wav_path)

    #Perform (or read) diarization
    if os.path.exists(out_mapped_json_path):
        #Load diarization dictionary
        print("Reading revised diarization output", out_mapped_json_path)
        with open(out_mapped_json_path, 'r') as f:
            diarization_dict_data = f.read()
            
        diarization_dict = json.loads(diarization_dict_data)
        if not skip_revision_query:
            skip_revision_query = True
            print("WARNING: Skipping diarization revision since revised diarization is found")
    elif os.path.exists(out_json_path):
        #Load diarization dictionary
        print("Reading raw diarization output", out_json_path)
        with open(out_json_path, 'r') as f:
            diarization_dict_data = f.read()
            
        diarization_dict = json.loads(diarization_dict_data)
    else:
        print("Performing diarization")
        diarization_dict = do_diarization(wav_path)

        #Write intermediate JSON to file
        with open(out_json_path, 'w') as f:
            print("Dumping raw diarization output", out_json_path)
            f.write(json.dumps(diarization_dict))

    #Print speakers data
    print_speakers_data(diarization_dict)

    do_revision = False
    if not skip_revision_query:
        #Perform speaker label revision (optional)
        perform_revision_input = input("Do you want to revise speaker labels? (y for yes) ")
        speaker_label_map_dict = {}
        
        if perform_revision_input == 'y' or perform_revision_input == 'Y':
            
            if os.path.exists(out_mapping_path):
                print("Found a mapping file with following info")
                with open(out_mapping_path, 'r') as f:
                    mapping_dict = f.read()
                
                speaker_label_map_dict = json.loads(mapping_dict)
                print(mapping_dict)
                use_savedmapping_input = input("Do you want to use it? (y for yes) ")
                if not use_savedmapping_input == 'y' and not use_savedmapping_input == 'Y':
                    do_revision = True
            else:
                do_revision = True

    if do_revision:
        #Open directory for revision
        if not os.path.exists(REVISION_PATH):
            os.makedirs(REVISION_PATH)

        #Do revision
        speaker_segments = {}
        for i, segment_info in enumerate(diarization_dict['content']):
            if segment_info['label'] not in speaker_segments:
                speaker_segments[segment_info['label']] = [i]
            else:
                speaker_segments[segment_info['label']].append(i)

        project_revision_path = os.path.join(revision_path, audio_id)

        if not os.path.exists(project_revision_path):
            os.makedirs(project_revision_path)

        print("Revise speaker samples from path " + project_revision_path)

        for spk in speaker_segments:
            print(spk)
            spk_utt_ids = speaker_segments[spk]
            pick_no = SAMPLE_COUNT if SAMPLE_COUNT < len(spk_utt_ids) else len(spk_utt_ids)
            
            pick = random.sample(spk_utt_ids, pick_no)
            
            #Open directory for spk under revision
            spk_revision_path = os.path.join(project_revision_path, spk)
            if not os.path.exists(spk_revision_path):
                os.makedirs(spk_revision_path)
            
            #Cut and place utterances under directory
            for utt_id in pick:
                utt_path = dump_chunk(complete_audio, 
                                      float(diarization_dict['content'][utt_id]['segment']['start']), 
                                      float(diarization_dict['content'][utt_id]['segment']['end']), 
                                      spk_revision_path)
                print(utt_path)
                
            print()

        print("Please specify names for each label")
        for spk in speaker_segments:
            mapto = input(spk + " is... ")
            speaker_label_map_dict[spk] = mapto
            
        with open(out_mapping_path, 'w') as f:
            print("Dumping mapping data", out_mapping_path)
            f.write(json.dumps(speaker_label_map_dict))

        print("Revised speaker labels")

        reversed_speaker_label_map_dict = {}
        for org_label in speaker_label_map_dict:
            new_label = speaker_label_map_dict[org_label]
            if new_label in reversed_speaker_label_map_dict:
                reversed_speaker_label_map_dict[new_label].append(org_label)
            else:
                reversed_speaker_label_map_dict[new_label] = [org_label]
            
        print(reversed_speaker_label_map_dict)

        #Update diarization dict with new label set
        mapped_diarization_dict = diarization_dict.copy()
        for segment in mapped_diarization_dict['content']:
            old_label = segment['label']
            segment['label'] = speaker_label_map_dict[old_label]

        #Write intermediate JSON to file
        with open(out_mapped_json_path, 'w') as f:
            print("Dumping mapped diarization output", out_mapped_json_path)
            f.write(json.dumps(mapped_diarization_dict))

        #Remove revision path
        shutil.rmtree(project_revision_path)
    else:
        mapped_diarization_dict = diarization_dict

    #Make empty OTR template
    print("Converting segments to turns")
    speaker_turns = get_speaker_turns(mapped_diarization_dict['content'], turn_on_segment, max_turn_length = max_turn_length)

    #print(speaker_turns) #DEBUG
    
    #Write empty template to disk
    print("Dumping diarized template", out_empty_otr_path)
    speaker_turns_to_otr(speaker_turns, out_empty_otr_path, write_speaker_id)

    if asr_service:
        #Create temp directory to store audio chunks
        tmp_dir_path = tempfile.mkdtemp()
        print("Temp dir:", tmp_dir_path) #DEBUG
        
        #Transcribe speaker turns
        for t in tqdm(speaker_turns, desc="Transcribing segments"):
            t['rawtext'], t['puncdtext'], t['wordtiming'] = get_transcription_of_chunk(complete_audio, t['start'], t['end'], tmp_dir_path, transcribe_func, speech_config)
            # print("%.2f-%.2f (%s): %s"%(t['start'], t['end'], t['speaker'], t['text']))

        #DEBUG
        #print("----")
        #for s in speaker_turns:
        #    print(s)
        #print("----")

        #Force max_turn_length if there's word timing information
        #TODO:...

        #Write transcribed turns to a JSON file
        with open(out_asr_path, 'w') as f:
            print("Dumping transcribed turns data", out_asr_path)
            f.write(json.dumps(speaker_turns))

        #Write transcribed template to disk
        print("Dumping transcribed template", out_final_otr_path)
        speaker_turns_to_otr(speaker_turns, out_final_otr_path, write_speaker_id)

        print("Dumping transcribed text", out_txt_path)
        speaker_turns_to_txt(speaker_turns, out_txt_path, write_speaker_id)

        print("Dumping SRT subtitles", out_srt_path)
        speaker_turns_to_srt(speaker_turns, out_srt_path, write_speaker_id)

        #Remove temp directory
        shutil.rmtree(tmp_dir_path) #DEBUG

if __name__ == "__main__":
    main()
