# IntelliCodeX practice pack

24 standalone practice programs: 8 languages x 3 difficulty levels.
These are intentionally imperfect debugging exercises, not production examples.
No bug locations, fix hints, answer key, or solution tests are included.

## Layout

Each language folder contains `01_easy`, `02_medium`, and `03_hard`.
CPP means C++. Choose ONE level folder at a time as your practice repository.
The tasks are equivalent across languages to allow comparison; these are not
24 unrelated algorithmic problems. Difficulty is relative within this pack.

## Intended behavior (task specification only)

### Easy: Invoice
Given a list of non-negative whole-number prices, return their total.
An empty list has total zero. Input sizes and values fit the numeric types used.

### Medium: Schedule
Given valid inclusive intervals [start, end], return their union as intervals
sorted by start, merging overlaps and intervals that share an endpoint.
Keep the input unchanged. Empty input produces empty output.
For C, callers supply an output array with room for at least count entries;
the function returns the number written, or -1 for allocation failure.

### Hard: Cache
Implement a least-recently-used cache for integer keys and non-negative integer
values. Capacity is 1 through 64. A successful get and every put count as usage.
When full, adding a new key evicts the least recently used entry. Updating an
existing key does not increase size. A missing key returns -1. Operations are
single-threaded. No specific time-complexity requirement is imposed.

The main/example block prints sample observations, not an answer key or test
verdict. Add your own inputs and assess behavior against the specification.

## Run locally

Run commands from the selected level folder. Replace invoice with schedule or
cache for other levels. Java class/file names start with a capital letter.
The appropriate compiler/runtime must already be installed.

| Language | Commands (one at a time) |
|---|---|
| Python | `python invoice.py` |
| JavaScript | `node invoice.js` |
| TypeScript | `tsc invoice.ts --target ES2020 --module commonjs --outDir dist`, then `node dist/invoice.js` |
| Java | `javac Invoice.java`, then `java Invoice` (JDK required) |
| C | `gcc -std=c11 invoice.c -o invoice`, then run the executable |
| C++ | `g++ -std=c++17 invoice.cpp -o invoice`, then run the executable |
| Go | `go run invoice.go` |
| Rust | `rustc --edition=2021 invoice.rs -o invoice`, then run the executable |

On Windows PowerShell run compiled executables with `.\invoice.exe`.
On Linux/macOS use `./invoice`.

## Use with IntelliCodeX

Point ingestion at one level folder, then ask it to explain or inspect the code.
You can copy the chosen file into your existing practice folder instead.
These are standalone source exercises: no pytest/JUnit/CTest/Cargo test suite
or project manifests are bundled. Automatic Docker behavioral verification
requires suitable tests and project configuration added separately.
There are no expected-output annotations or bug-location comments in source.
