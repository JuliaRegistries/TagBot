from typing import Literal

class QueueType:
    def send_message(self, *, MessageBody: str, DelaySeconds: int) -> object: ...

class SQS:
    @staticmethod
    def Queue(url: str) -> QueueType: ...

def resource(name: Literal["sqs"], *, region_name: str) -> SQS: ...
