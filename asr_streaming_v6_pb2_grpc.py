# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
import grpc

import asr_streaming_v6_pb2 as asr__streaming__pb2


class SpeechRecognitionStub(object):
  # missing associated documentation comment in .proto file
  pass

  def __init__(self, channel):
    """Constructor.

    Args:
      channel: A grpc.Channel.
    """
    self.RecognizeStream = channel.stream_stream(
        '/SpeechRecognition/RecognizeStream',
        request_serializer=asr__streaming__pb2.StreamingSpeechRequest.SerializeToString,
        response_deserializer=asr__streaming__pb2.StreamingSpeechResponse.FromString,
        )


class SpeechRecognitionServicer(object):
  # missing associated documentation comment in .proto file
  pass

  def RecognizeStream(self, request_iterator, context):
    # missing associated documentation comment in .proto file
    pass
    context.set_code(grpc.StatusCode.UNIMPLEMENTED)
    context.set_details('Method not implemented!')
    raise NotImplementedError('Method not implemented!')


def add_SpeechRecognitionServicer_to_server(servicer, server):
  rpc_method_handlers = {
      'RecognizeStream': grpc.stream_stream_rpc_method_handler(
          servicer.RecognizeStream,
          request_deserializer=asr__streaming__pb2.StreamingSpeechRequest.FromString,
          response_serializer=asr__streaming__pb2.StreamingSpeechResponse.SerializeToString,
      ),
  }
  generic_handler = grpc.method_handlers_generic_handler(
      'SpeechRecognition', rpc_method_handlers)
  server.add_generic_rpc_handlers((generic_handler,))
