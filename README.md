```
python -m grpc_tools.protoc -I ./xud/proto --python_out=. --grpc_python_out=. ./xud/proto/xudrpc.proto
python -m grpc_tools.protoc -I ./xud/proto --python_out=. ./xud/proto/annotations.proto
python -m grpc_tools.protoc -I ./xud/proto --python_out=. ./xud/proto/google/api/http.proto
python -m grpc_tools.protoc -I ./xud/proto --python_out=. ./xud/proto/google/protobuf/descriptor.proto
```