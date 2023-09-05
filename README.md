# FatCat Server
This is the FatCat Server

This component listens to the `incoming` queue in RabbitMQ, validates and modifies the message according to the end-queue's schemas (located in the MongoDB), and sends the result to teh end-queue. Please refer to [config-example.yml](config-example.yml) for a configuration example.

Don't forget to check [.env-example](.env-example) for a `.env` example.