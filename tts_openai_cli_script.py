from more_itertools import batched
import asyncio
import itertools
import re
import argparse
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv
from dotenv import dotenv_values, find_dotenv
from pathlib import Path
import time
import subprocess
import hashlib


def hash_file_name(file_name):
    sha256_hash = hashlib.md5()
    sha256_hash.update(file_name.encode('utf-8'))
    return sha256_hash.hexdigest()


def concatenate_audio_files(input_files, lists_txt, output_file, keep):
    with open(lists_txt, "w") as f:
        for i in input_files:
            if i is not None:
                f.write("file '{}'\n".format(i))
        list_file_path = f.name

    ffmpeg_cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_file_path, '-codec', 'copy', output_file]
    print(f"{ffmpeg_cmd=}")
    subprocess.run(ffmpeg_cmd)
    
    if not keep:
        for f in (*input_files, list_file_path):
            os.remove(f)


async def wait_until_next_minute():
    current_time = time.localtime()
    seconds_until_next_minute = 60 - current_time.tm_sec
    print(f"waiting for next minute to start: {seconds_until_next_minute} seconds")
    await asyncio.sleep(seconds_until_next_minute)


async def stream_to_file(client, model, voice, input, response_format, output_file):

    async with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=input,
        response_format=response_format
    ) as response:
        print(f"started streaming to '{output_file}'")
        await response.stream_to_file(output_file)

    return output_file


async def generate_audio(input_file, voice="alloy", model="tts-1", keep=False, rpm=3):
    hash = hash_file_name(input_file)
    temp_files = []
    dotenv_path = '.env'
    load_dotenv(dotenv_path)

    with open(input_file, "r") as f:
        input_text = f.read()

    sections = split_string(input_text, max_length=4096)

    stem = Path(input_file).stem

    client = AsyncOpenAI()
    key = "OPENAI_SPEECH_RPM"

    if rpm == 3:
        env_rpm = os.getenv(key)
        if env_rpm.isdigit():
            rpm = int(env_rpm)

    batch_size = rpm
        
    total_batches = len(sections) // batch_size + (1 if len(sections) % batch_size != 0 else 0)
    print(f"{total_batches=}")

    for j, batch in enumerate(batched(sections, batch_size)):

        temp_files.extend(await asyncio.gather(*(stream_to_file(
            client, model, voice, a, 'aac', f"{stem} part {i+j*3} {hash}.m4a")
                for i, a in enumerate(batch)), *([] if j+1 == total_batches  else [wait_until_next_minute()])))

    concatenate_audio_files(temp_files, f"{stem} lists {hash}.txt", "output.m4a", keep)


def split_string(text, max_length):
    sentences = re.split(r'(?=\.\s+[A-Z])', text)
    o = [*itertools.accumulate(sentences, lambda a,x: len(x) if (a+len(x)) > max_length else a+len(x), initial=0)]
    groups = [[]]
    for s, c in zip(sentences, o):
        if c + len(s) > max_length:
            groups.append([s])
        else:
            groups[-1].append(s)

    return ["".join(g) for g in groups]


def main():
    parser = argparse.ArgumentParser(description="CLI for OpenAI's tts API")
    parser.add_argument("input_file", help="Path to the input text file")
    parser.add_argument("--voice", default="alloy", help="Voice for text-to-speech (default: alloy, echo, fable, onyx, nova, and shimmer)")
    parser.add_argument('--hd', '-hd', action='store_true', help='Use high definition model (tts-1-hd)')
    parser.add_argument('--keep', '-k', action='store_true', help='Keep intermediate files')
    parser.add_argument('--rpm', type=int, default=3, help='Requests per minute (default: 3) OPENAI_SPEECH_RPM enviroment variable will override the default')


    args = parser.parse_args()

    asyncio.run(generate_audio(args.input_file, voice=args.voice, model='tts-1-hd' if args.hd else 'tts-1', keep=args.keep, rpm=args.rpm))


if __name__ == "__main__":
    main()

