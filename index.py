#!/usr/bin/env python

import io
import os
import socket
from subprocess import Popen, PIPE
from threading import Thread
from time import sleep

from dotenv import load_dotenv
import picamera


dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

WIDTH = 640
HEIGHT = 480
FRAMERATE = 24
CAMERA_ID = os.environ.get('CAMERA_ID')
MONITOR_IP = os.environ.get('MONITOR_IP', '127.0.0.1')
TCP_PORT = os.environ.get('TCP_PORT', 5005)


class MyException(Exception):
    pass


class BroadcastOutput(object):
    def __init__(self, camera):
        print('Spawning background conversion process')
        self.converter = Popen([
            'avconv',
            '-f', 'rawvideo',
            '-pix_fmt', 'yuv420p',
            '-s', '%dx%d' % camera.resolution,
            '-r', str(float(camera.framerate)),
            '-i', '-',
            '-f', 'mpeg1video',
            '-b', '800k',
            '-r', str(float(camera.framerate)),
            '-'],
            stdin=PIPE, stdout=PIPE, stderr=io.open(os.devnull, 'wb'),
            shell=False, close_fds=True)

    def write(self, b):
        self.converter.stdin.write(b)

    def flush(self):
        print('Waiting for background conversion process to exit')
        self.converter.stdin.close()
        self.converter.wait()


class BroadcastThread(Thread):
    def __init__(self, converter, socket_client):
        super(BroadcastThread, self).__init__()
        self.converter = converter
        self.socket_client = socket_client

    def run(self):
        try:
            while True:
                buf = self.converter.stdout.read(512)
                if buf:
                    self.socket_client.send(CAMERA_ID + '|' + buf)
                elif self.converter.poll() is not None:
                    break
        finally:
            self.converter.stdout.close()
            self.socket_client.send(CAMERA_ID + '|' 'finish')


def main():
    try:
        socket_client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_client.connect((MONITOR_IP, TCP_PORT))
        socket_client.send(CAMERA_ID + '|' 'start')
        print('Ready!')

        while True:
            data = socket_client.recv(1024)

            if len(data) == 0:
                print('Reconnect!')
                socket_client.connect((MONITOR_IP, TCP_PORT))
                socket_client.send(CAMERA_ID + '|' 'start')

            if data == 'record':
                print('Initializing camera')

                with picamera.PiCamera() as camera:
                    camera.resolution = (WIDTH, HEIGHT)
                    camera.framerate = FRAMERATE
                    sleep(1)  # camera warm-up time
                    print('Initializing broadcast thread')
                    output = BroadcastOutput(camera)
                    broadcast_thread = BroadcastThread(
                        output.converter, socket_client)
                    print('Starting recording')
                    camera.start_recording(output, 'yuv')
                    print('Starting broadcast thread')
                    broadcast_thread.start()

                    while True:
                        camera.wait_recording(1)
                        data = socket_client.recv(1024)

                        if data == 'stop':
                            print('Stopping recording')
                            camera.stop_recording()
                            print('Waiting for broadcast thread to finish')
                            broadcast_thread.join()
                            break

    except Exception as e:
        print(e)
        pass

    finally:
        socket_client.close()


if __name__ == '__main__':
    if not CAMERA_ID:
        raise MyException('Error: Set CAMERA_ID')
    main()
