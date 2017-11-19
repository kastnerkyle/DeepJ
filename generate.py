import numpy as np
import argparse
import heapq

import torch
import torch.nn as nn
from torch.autograd import Variable
from tqdm import trange

from midi_io import *
from dataset import *
from constants import *
from util import *
from model import DeepJ

class Generation():
    """
    Represents a music generation sequence
    """

    def __init__(self, model, style=None, default_temp=1, beam_size=1):
        self.model = model

        self.beam_size = beam_size

        # Pick a random style
        self.style = style if style is not None else one_hot(np.random.randint(0, NUM_STYLES), NUM_STYLES)

        # Temperature of generation
        self.default_temp = default_temp
        self.temperature = self.default_temp
        # How much time of silence
        self.silent_time = SILENT_LENGTH

        # Progress of generated music between 0 and 1
        self.progress = 0
        # Clock input that resets every second
        self.progress_clock = [0, 0]

        # Model parametrs
        self.beam = [
            (1, tuple(), None, self.progress)
        ]
        self.avg_seq_prob = 1
        self.step_count = 0

    def step(self, seq_len):
        """
        Generates the next set of beams
        """
        # Create variables
        style = var(to_torch(self.style), volatile=True).unsqueeze(0)

        new_beam = []
        sum_seq_prob = 0

        # Iterate through the beam
        for prev_prob, evts, state, progress in self.beam:
            if len(evts) > 0:
                prev_event = var(to_torch(one_hot(evts[-1], NUM_ACTIONS)), volatile=True).unsqueeze(0)
                if evts[-1] >= TIME_OFFSET and evts[-1] < TIME_OFFSET + TIME_QUANTIZATION:
                    progress_in_sec = (TICK_BINS[evts[-1] - TIME_OFFSET] / TICKS_PER_SEC)
                    progress += progress_in_sec / seq_len
                    self.progress = progress
                    self.progress_clock = [np.cos(progress_in_sec), np.sin(progress_in_sec)]
            else:
                prev_event = var(torch.zeros((1, NUM_ACTIONS)), volatile=True)

            prev_event = prev_event.unsqueeze(1)
            progress_tensor = var(torch.FloatTensor([self.progress_clock])).unsqueeze(0)
            probs, new_state = self.model.generate(prev_event, style, progress_tensor, state, temperature=self.temperature)
            probs = probs[0].cpu().data.numpy()

            for _ in range(self.beam_size):
                # Sample action
                output = batch_sample(probs)
                # output = np.argmax(probs, axis=1)
                event = output[0]
                
                # Create next beam
                seq_prob = prev_prob * probs[0, event]
                new_beam.append((seq_prob / self.avg_seq_prob, evts + (event,), new_state, progress))
                sum_seq_prob += seq_prob

        self.avg_seq_prob = sum_seq_prob / len(new_beam)
        # Find the top most probable sequences
        self.beam = heapq.nlargest(self.beam_size, new_beam, key=lambda x: x[0])
        self.step_count += 1

    def generate(self, seq_len=30):
        while self.progress <= 1:
            self.step(seq_len)

        best = max(self.beam, key=lambda x: x[0])
        best_seq = best[1]
        return np.array(best_seq)

    def export(self, name='output', seq_len=30):
        """
        Export into a MIDI file.
        """
        seq = self.generate(seq_len)
        save_midi(name, seq)

def main():
    parser = argparse.ArgumentParser(description='Generates music.')
    parser.add_argument('--path', help='Path to model file')
    parser.add_argument('--length', default=30, type=int, help='Length of generation in seconds')
    parser.add_argument('--style', default=None, type=int, nargs='+', help='Styles to mix together')
    parser.add_argument('--temperature', default=1, type=float, help='Temperature of generation')
    parser.add_argument('--beam', default=1, type=int, help='Beam size')
    args = parser.parse_args()

    style = None

    if args.style:
        # Custom style
        style = np.mean([one_hot(i, NUM_STYLES) for i in args.style], axis=0)

    print('=== Loading Model ===')
    print('Path: {}'.format(args.path))
    print('GPU: {}'.format(torch.cuda.is_available()))
    settings['force_cpu'] = True
    
    model = DeepJ()

    if args.path:
        model.load_state_dict(torch.load(args.path))
    else:
        print('WARNING: No model loaded! Please specify model path.')

    print('=== Generating ===')
    Generation(model, style=style, default_temp=args.temperature, beam_size=args.beam).export(seq_len=args.length)

if __name__ == '__main__':
    main()
