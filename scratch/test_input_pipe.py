import subprocess
import sys

def test():
    proc = subprocess.Popen(
        [sys.executable, "-c", "x = input('prompt: '); print(f'GOT:{x}')"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate(input="hello\n", timeout=5)
    print("OUTPUT:", repr(out))

if __name__ == "__main__":
    test()
