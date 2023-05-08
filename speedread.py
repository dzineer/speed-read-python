import sys
import time
import tty
import termios
import argparse
import math
from select import select
from typing import List, Tuple
import re
from termcolor import colored
from colorama import Fore, Back, Style
import argparse
import termios
import string
import shutil

# get the size of the terminal
terminal_size = shutil.get_terminal_size()

word = "MY WORD"

# calculate the number of spaces needed to center the text
padding = " " * ((terminal_size.columns - len(word)) // 2)

# print the word centered on the screen
# print(padding + "MY WORD")

# Constants

WORDTIME = 0.9  # relative to wpm
LENTIME = 0.04  # * sqrt(length $word), relative to wpm
COMMATIME = 2  # relative to wpm
FSTOPTIME = 3  # relative to wpm
MULTITIME = 1.2  # relative to wpm
FIRSTTIME = 0.2  # [s]
ORPLOC = 0.35
ORPMAX = 0.2
ORPVISUALPOS = 20
CURSORPOS = 64

# Global variables

wpm = 250
resume = 0
multiword = False

word_counter = 0
letter_counter = 0
last_lines = ["", "", ""]
current_word = ""
current_orp = 0
next_word_time = 0
next_input_time = 0
skipped = 0
paused = False
tty_fd = None
t0 = time.time()  # Define t0 variable here

# Helper functions


def print_stats():
    elapsed = time.monotonic() - t0
    truewpm = wordcounter / elapsed * 60
    print(f"\n {elapsed:.2f}s, {wordcounter} words, {lettercounter} letters, "
          f"{colored('bold green', 'green')}{truewpm:.2f}{colored('reset')} true wpm")


def handle_sigint(sig, frame) -> None:
    print_stats()
    resume_word = word_counter + resume
    print(f" To resume from this point run with argument -r {resume_word}")
    sys.exit(0)


def find_orp(word: str, orp_loc: float) -> int:
    if len(word) > 13:
        return 4
    return [0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3][len(word)]


def show_guide() -> None:
    # Top visual guide
    print(" " * ORPVISUALPOS + "\033[31mv\033[0m\033[K")


def show_word2(word: str, i: int) -> None:
    """
    Displays the given word with a pivot character at the given index.
    """
    if i < len(word):
        pivotch = word[i]
    else:
        pivotch = ""

    # Calculate the width of the terminal
    width = shutil.get_terminal_size().columns

    # Calculate the padding on either side of the word
    left_padding = (width - len(word)) // 2
    right_padding = width - len(word) - left_padding

    # Construct the centered word with ANSI color codes
    centered_word = (' ' * left_padding +
                     Style.BOLD + Fore.BLUE + word[:i] +
                     Fore.RED + pivotch + Fore.BLUE + word[i+1:] +
                     Back.END + ' ' * right_padding)

    # Print the centered word
    sys.stdout.write(centered_word)
    sys.stdout.flush()


def show_word(word: str, i: int) -> None:
    """
    Displays the given word with a pivot character at the given index.
    """
    if i < len(word):
        pivotch = word[i]
    else:
        pivotch = ""
    sys.stdout.write(Style.BRIGHT + Fore.BLUE + word[:i] + Fore.RED + pivotch +
                     Fore.BLUE + word[i+1:] + Style.RESET_ALL + ' ')
    sys.stdout.flush()


def word_time(word: str) -> float:
    global word_counter, letter_counter

    time_ = WORDTIME
    if word.endswith((".", "!", "?")):
        time_ = FSTOPTIME
    elif word.endswith((",", ";", ":")):
        time_ = COMMATIME
    elif " " in word:
        time_ = MULTITIME
    time_ += math.sqrt(len(word)) * LENTIME
    time_ *= 60 / wpm

    # Give user some time to focus on the first word, even with high wpm.
    if word_counter == 0 and time_ < FIRSTTIME:
        time_ = FIRSTTIME

    word_counter += 1
    letter_counter += len(word)

    return time_


def print_context(wn: int) -> None:
    # One line up and to its beginning
    print("\r\033[K\033[A\033[K", end="")
    # First line of context
    if last_lines[1]:
        print(last_lines[1])
    # In second line of context, highlight our word
    line0 = last_lines[0]
    c0 = "\033[33m"
    c1 = "\033[0m"
    line0 = f"{c0}{line0[:wn]}{c1}{line0[wn:]}".replace("-", c0 + "-" + c1)
    print(line0)


def join_short_words(words: List[str]) -> List[str]:
    """
    Join adjacent short words (3 characters or less) together in the list of words.
    """
    i = 0
    new_words = []
    while i < len(words):
        if len(words[i]) <= 3 and i < len(words) - 1 and len(words[i+1]) <= 3:
            new_words.append(words[i] + ' ' + words[i+1])
            i += 2
        else:
            new_words.append(words[i])
            i += 1
    return new_words


def process_keys(word: str, i: int, wn: int) -> None:
    global paused, next_word_time

    while select([tty_fd], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if ch == "[":
            global wpm
            wpm = int(wpm * 0.9)
        elif ch == "]":
            wpm = int(wpm * 1.1)
        elif ch == " ":
            paused = not paused
            if paused:
                # Print context.
                print_context(wn)
                show_guide()
                show_word2(word, i)
            else:
                next_word_time = time.time()


class rawinput:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.original_attr = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)

    def __del__(self):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.original_attr)

    def key_pressed(self):
        import select
        return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])

    def getch(self):
        return sys.stdin.read(1)


def replace_punctuation(s: str) -> str:
    """
    Replace punctuation marks in the string with spaces.
    """
    return ''.join(c if c not in string.punctuation else ' ' for c in s).strip()


def wait_for_word(word: str, wpm: int, word_delay: float = 0.05) -> float:
    """
    Waits for the duration of the given word at the given WPM.
    Returns the actual duration of the word.
    """
    # Estimate time for word at given WPM
    duration = len(word) * 60 / (wpm * 1000)
    start_time = time.time()
    end_time = start_time + duration

    # Delay for a fraction of the duration before returning
    time.sleep(duration / 10)

    while time.time() < end_time:
        time.sleep(word_delay)

    return time.time() - start_time


def main() -> None:
    parser = argparse.ArgumentParser(description='Speed reader')
    parser.add_argument('file_path', metavar='FILE',
                        type=str, help='path of the file to read')
    parser.add_argument('-w', '--wpm', type=int, default=300,
                        help='words per minute (default: 300)')
    parser.add_argument('-r', '--resume', type=int, default=0,
                        help='resume from a specific word index (default: 0)')
    parser.add_argument('-m', '--monitor', action='store_true',
                        help='display reading statistics')
    parser.add_argument('-s', '--speed', type=float, default=0.5,
                        help='reading speed as a float (default: 0.5)')
    args = parser.parse_args()

    # Read file.
    with open(args.file_path, 'r') as f:
        text = f.read()

    # Preprocess text.
    # text = join_short_words(text)
    text = replace_punctuation(text)
    words = text.split()

    # Initialize variables.
    global wordcounter, lettercounter, paused, next_word_time, wpm
    wordcounter = 0
    lettercounter = 0
    paused = False
    next_word_time = time.time()
    wpm = args.wpm
    speed = args.speed

    # Show guide.
    show_guide()

    # Loop through words.
    i = args.resume
    # Loop through words.
    for i, word in enumerate(words[args.resume:]):
        if paused:
            # Print context.
            print_context(i)
            show_guide()
            show_word(word, i)
            # Wait for user input to resume.
            while paused:
                process_keys(word, i, args.resume + i)
                time.sleep(0.01)
        else:
            show_word(word, i)
            wait_for_word(word, args.wpm, args.speed)
            sys.stdout.write('\r' + ' ' * 80 + '\r')  # clear previous word

        # Update counters.
        wordcounter += 1
        lettercounter += len(word)

    # Print statistics.
    if args.monitor:
        print_stats()


main()
