import boto3
import json

from . import env


class SNS:
    _sns = boto3.client("sns")

    def publish(self, topic, message):
        topic = env.sns_topic(topic)
        self._sns.publish(TopicArn=topic, Message=json.dumps(message))
