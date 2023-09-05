import logging
import asyncio
import json
import os
from datetime import datetime
from .exceptions import MongoInsertException

import aio_pika
from fatcat_utils.rabbitmq import \
    RabbitMQHandler, RABBIT_CONFIG, AckTime, MessageStatus
from fatcat_utils.logger import generate_logger
from fatcat_utils.mongodb import DatabaseHandler
from fatcat_utils.schema_validator import match_to_schema


class Server:
    """This is the Server class.

    Nothing much to tell really. Just a class for the server, 
    contains all the server functiona and listeners
    """
    rabbit: RabbitMQHandler = RabbitMQHandler()
    mongo: DatabaseHandler = DatabaseHandler()
    logger: logging.Logger = generate_logger(f"FatCatServer{os.getenv('FATCAT_SERVER_NAME')}Logger")
    
    def run(self):
        """The run function.

        Call this function to start the worker.
        """
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start())
        loop.call_later(5, self.check_listeners_status)
        loop.run_forever()

    async def start(self):
        """THe start function.
        
        Sets up the mongo and connectes to the rabbit
        """
        self.logger.info("Starting up the Rabbit handler")
        await self.rabbit.connect()
        self.logger.info("Rabbit handler was been connected")
        self.logger.info("Setting up the Mongo environment")
        await self.mongo.setup()
        self.logger.info("Mongo has been set up")

    @rabbit.subscribe(RABBIT_CONFIG["incoming_queue"], ack=AckTime.Manual)
    @staticmethod
    async def handle_incoming(message: aio_pika.IncomingMessage) -> MessageStatus:
        """Handles the incoming queue

        :param message: The RabbitMQ message
        :type message: aio_pika.IncomingMessage
        :return: The status of the message after the function finishes
        :rtype: MessageStatus
        """
        message.body = message.body.decode("utf-8")

        if "FATCAT_QUEUE_TAG" not in message.body:
            Server.logger.error("Message missing FATCAT_QUEUE_TAG tag. Sending it to the failed queue.")
            await message.reject()
            Server.rabbit.send_to_queue(message.body, RABBIT_CONFIG["failed_queue"])
            return MessageStatus.Rejected
        
        try:
            body: dict = json.loads(message.body)
        except json.JSONDecodeError:
            Server.logger.error("Message couldn't be parsed as json. To the failed queue!")
            await message.reject()
            Server.rabbit.send_to_queue(message.body, RABBIT_CONFIG["failed_queue"])
            return MessageStatus.Rejected
        
        queue = await Server.mongo.get_queue(body)
        if queue is None or queue == {}:
            Server.logger.error("Couldn't find the correct queue. To the failed queue!")
            await message.reject()
            Server.rabbit.send_to_queue(message.body, RABBIT_CONFIG["failed_queue"])
            return MessageStatus.Rejected
        
        if not len(queue["schemas"]) == 0:
            for schema in queue["schemas"]:
                new_body = await match_to_schema(body, schema)
                if new_body is not None:
                    break
            else:
                Server.logger.error("Message doesn't meet any of the queue's schemas. To the failed queue!")
                await message.reject()
                return MessageStatus.Rejected
        else:
            new_body = body

        Server.logger.info(f"Sending the message to the queue {queue['queue_name']}")
        await Server.rabbit.send_to_queue(new_body, queue["queue_name"])
        await message.ack()
        return MessageStatus.Acked
    
    @rabbit.subscribe(RABBIT_CONFIG["failed_queue"], ack=AckTime.End)
    @staticmethod
    async def handle_failed(message: aio_pika.IncomingMessage):
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
                await Server.mongo.add_fail(body)
            except:
                pass
            else:
                break
        else:
            raise MongoInsertException("Couldn't insert the failed message into the DB")
        Server.logger.info("Added failed message to Database")

    @rabbit.subscribe(os.getenv("FATCAT_RABBIT_WORKER_FAILED_QUEUE", "worker-failed"), ack=AckTime.End)
    @staticmethod
    async def handle_worker_failed(message: aio_pika.IncomingMessage):
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
                await Server.mongo.add_worker_fail(body)
            except:
                pass
            else:
                break
        else:
            raise MongoInsertException("Couldn't insert the failed message into the DB")
        Server.logger.info("Added failed message to Database")

    def check_listeners_status(self):
        """Checks if there are any active listeners. If not, kills the program.
        """
        loop = asyncio.get_event_loop()
        if len(self.rabbit._background_listeners) == 0:
            loop.call_later(0.1, self.rabbit.close)  # Hacky hack
            loop.stop()
        else:
            loop.call_later(5, self.check_listeners_status)
