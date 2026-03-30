import json
from confluent_kafka import Producer, Consumer, KafkaError
from src.config import settings

class KafkaManager:
    def __init__(self):
        self.producer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'client.id': 'ccirp-producer'
        }
        self.consumer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': 'ccirp-group',
            'auto.offset.reset': 'earliest'
        }
        self.producer = None

    def get_producer(self):
        if self.producer is None:
            self.producer = Producer(self.producer_config)
        return self.producer

    def produce_message(self, topic, message):
        producer = self.get_producer()
        producer.produce(topic, json.dumps(message).encode('utf-8'))
        producer.flush()

    def consume_messages(self, topics):
        consumer = Consumer(self.consumer_config)
        consumer.subscribe(topics)

        try:
            while True:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        print(f"Kafka error: {msg.error()}")
                        break
                
                yield json.loads(msg.value().decode('utf-8'))
        finally:
            consumer.close()

kafka_manager = KafkaManager()
