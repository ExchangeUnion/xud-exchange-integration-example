### How to run

Clone this repository then update `xud` submodule

```bash
git submodule update
```

Make sure you have `virtualenv` command in your local system. 

```bash
which virtualenv
```

If `virtualenv` is not installed in your system then install it by

```bash
pip install virtualenv
```

Create a python virtual environment. Specify `-p` with your local python 3 executable name (maybe `python3`, `python3.6`, `python3.7`, etc.)

```bash
virtualenv -p python3 --no-site-packages venv
```

Active your installed virtual environment. You can deactive it by just typing `deactive` later.

```bash
venv/bin/active
```

Install python dependencies

```bash
pip install -r requirements.txt
```

Compile gRPC protocols

```bash
python -m grpc_tools.protoc -I ./xud/proto --python_out=. --grpc_python_out=. ./xud/proto/xudrpc.proto
python -m grpc_tools.protoc -I ./xud/proto --python_out=. ./xud/proto/annotations.proto
python -m grpc_tools.protoc -I ./xud/proto --python_out=. ./xud/proto/google/api/http.proto
python -m grpc_tools.protoc -I ./xud/proto --python_out=. ./xud/proto/google/protobuf/descriptor.proto
```

Run this example

```bash
python engine.py
```

You can type `help` for more helps in the running example.