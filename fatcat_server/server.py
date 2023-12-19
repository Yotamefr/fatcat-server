import json
import os
from datetime import datetime
import aio_pika
from fatcat_utils import FatCat
from fatcat_utils.mongodb.exceptions import MongoInsertException
from fatcat_utils.rabbitmq import RABBIT_CONFIG, AckTime, MessageStatus, ListenerGroup
from fatcat_utils.schema_validator import match_to_schema


class Server(ListenerGroup):
    """This is the Server class.

    Nothing much to tell really. Just a class for the server, 
    contains all the server functiona and listeners
    """

    def __init__(self, fatcat: FatCat):
        self.fatcat = fatcat

    @FatCat.create_listener(RABBIT_CONFIG["incoming_queue"], ack_time=AckTime.Manual)
    async def handle_incoming(self, message: aio_pika.IncomingMessage) -> MessageStatus:
        """Handles the incoming queue

        :param message: The RabbitMQ message
        :type message: aio_pika.IncomingMessage
        :return: The status of the message after the function finishes
        :rtype: MessageStatus
        """
        message.body = message.body.decode("utf-8")

        if "FATCAT_QUEUE_TAG" not in message.body:
            self.fatcat.logger.error("Message missing FATCAT_QUEUE_TAG tag. Sending it to the failed queue.")
            await message.reject()
            self.fatcat.rabbit.send_to_queue(message.body, RABBIT_CONFIG["failed_queue"])
            return MessageStatus.Rejected
        
        try:
            body: dict = json.loads(message.body)
        except json.JSONDecodeError:
            self.fatcat.logger.error("Message couldn't be parsed as json. To the failed queue!")
            await message.reject()
            self.fatcat.rabbit.send_to_queue(message.body, RABBIT_CONFIG["failed_queue"])
            return MessageStatus.Rejected
        
        queue = await self.fatcat.mongo.get_queue(body)
        if queue is None or queue == {}:
            self.fatcat.logger.error("Couldn't find the correct queue. To the failed queue!")
            await message.reject()
            self.fatcat.rabbit.send_to_queue(message.body, RABBIT_CONFIG["failed_queue"])
            return MessageStatus.Rejected
        
        if not len(queue["schemas"]) == 0:
            for schema in queue["schemas"]:
                new_body = await match_to_schema(body, schema)
                if new_body is not None:
                    break
            else:
                self.fatcat.logger.error("Message doesn't meet any of the queue's schemas. To the failed queue!")
                await message.reject()
                return MessageStatus.Rejected
        else:
            new_body = body

        self.fatcat.logger.info(f"Sending the message to the queue {queue['queue_name']}")
        await self.fatcat.rabbit.send_to_queue(new_body, queue["queue_name"])
        await message.ack()
        return MessageStatus.Acked
    
    @FatCat.create_listener(RABBIT_CONFIG["failed_queue"], ack_time=AckTime.End)
    async def handle_failed(self, message: aio_pika.IncomingMessage):
        """Handles the failed messages from the RabbitMQ

        :param message: The RabbitMQ message
        :type message: aio_pika.IncomingMessage
        :raises MongoInsertException: Failed to insert the message to the DB
        """
        try:
            body = json.loads(message.body.decode("utf-8"))
        except:
            body = {
                "message_body": message.body
            }

        if "FATCAT_TIMESTAMP" not in body:
            body["FATCAT_TIMESTAMP"] = datetime.now()

        for _ in range(3):
            try:
                await self.fatcat.mongo.add_fail(body)
            except:
                pass
            else:
                break
        else:
            raise MongoInsertException("Couldn't insert the failed message into the DB")
        self.fatcat.logger.info("Added failed message to Database")

    @FatCat.create_listener(os.getenv("FATCAT_RABBIT_WORKER_FAILED_QUEUE", "worker-failed"), ack_time=AckTime.End)
    async def handle_worker_failed(self, message: aio_pika.IncomingMessage):
        """Handles the failed messages from the RabbitMQ

        :param message: The RabbitMQ message
        :type message: aio_pika.IncomingMessage
        :raises MongoInsertException: Failed to insert the message to the DB
        """
        try:
            body = json.loads(message.body.decode("utf-8"))
        except:
            body = {
                "message_body": message.body
            }

        if "FATCAT_TIMESTAMP" not in body:
            body["FATCAT_TIMESTAMP"] = datetime.now()
        
        for _ in range(3):
            try:
                await self.fatcat.mongo.add_worker_fail(body)
            except:
                pass
            else:
                break
        else:
            raise MongoInsertException("Couldn't insert the failed message into the DB")
        self.fatcat.logger.info("Added failed message to Database")
