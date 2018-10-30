from enum import Enum

from matrix.common.dynamo_handler import DynamoHandler, DynamoTable, StateTableField, OutputTableField
from matrix.common.logging import Logging

logger = Logging.get_logger(__name__)


class Subtask(Enum):
    """
    A Subtask represents a processing stage in a matrix service request.

    Driver - daemons/driver.py
    Mapper - daemons/mapper.py
    Worker - daemons/worker.py
    Reducer - daemons/reducer.py
    Converter - common/matrix_converter.py
    """
    DRIVER = "driver"
    MAPPER = "mapper"
    WORKER = "worker"
    REDUCER = "reducer"
    CONVERTER = "converter"


class RequestTracker:
    """
    Provides an interface for tracking a request's parameters and state.
    """
    def __init__(self, request_id: str):
        Logging.set_correlation_id(logger, request_id)

        self.request_id = request_id
        self._format = None

        self.dynamo_handler = DynamoHandler()

    @property
    def format(self) -> str:
        """
        The request's user specified output file format of the resultant expression matrix.
        :return: str The file format (one of MatrixFormat)
        """
        if not self._format:
            self._format = self.dynamo_handler.get_table_item(DynamoTable.OUTPUT_TABLE,
                                                              self.request_id)[OutputTableField.FORMAT.value]
        return self._format

    @property
    def error(self) -> str:
        """
        The user-friendly message describing the latest error the request raised.
        :return: str The error message if one exists, else empty string
        """
        error = self.dynamo_handler.get_table_item(DynamoTable.OUTPUT_TABLE,
                                                   self.request_id)[OutputTableField.ERROR_MESSAGE.value]

        if error:
            return error
        return ""

    def init_request(self, num_mappers: int, format: str):
        """
        Creates a new request in the relevant DynamoDB tables for state and output tracking.
        :param num_mappers: Number of expected mapper nodes this request will run.
        :param format: The request's user specified output file format of the resultant expression matrix.
        """
        self.dynamo_handler.create_state_table_entry(self.request_id, num_mappers, format)
        self.dynamo_handler.create_output_table_entry(self.request_id, format)

    def expect_subtask_execution(self, subtask: Subtask):
        """
        Expect the execution of 1 Subtask by tracking it in DynamoDB.
        A Subtask is executed either by a Lambda or AWS Batch.
        :param subtask: The expected Subtask to be executed.
        """
        subtask_to_dynamo_field_name = {
            Subtask.DRIVER: StateTableField.EXPECTED_DRIVER_EXECUTIONS,
            Subtask.MAPPER: StateTableField.EXPECTED_MAPPER_EXECUTIONS,
            Subtask.WORKER: StateTableField.EXPECTED_WORKER_EXECUTIONS,
            Subtask.REDUCER: StateTableField.EXPECTED_REDUCER_EXECUTIONS,
            Subtask.CONVERTER: StateTableField.EXPECTED_CONVERTER_EXECUTIONS,
        }

        self.dynamo_handler.increment_table_field(DynamoTable.STATE_TABLE,
                                                  self.request_id,
                                                  subtask_to_dynamo_field_name[subtask],
                                                  1)

    def complete_subtask_execution(self, subtask: Subtask):
        """
        Counts the completed execution of 1 Subtask in DynamoDB.
        A Subtask is executed either by a Lambda or AWS Batch.
        :param subtask: The executed Subtask.
        """
        subtask_to_dynamo_field_name = {
            Subtask.DRIVER: StateTableField.COMPLETED_DRIVER_EXECUTIONS,
            Subtask.MAPPER: StateTableField.COMPLETED_MAPPER_EXECUTIONS,
            Subtask.WORKER: StateTableField.COMPLETED_WORKER_EXECUTIONS,
            Subtask.REDUCER: StateTableField.COMPLETED_REDUCER_EXECUTIONS,
            Subtask.CONVERTER: StateTableField.COMPLETED_CONVERTER_EXECUTIONS,
        }

        self.dynamo_handler.increment_table_field(DynamoTable.STATE_TABLE,
                                                  self.request_id,
                                                  subtask_to_dynamo_field_name[subtask],
                                                  1)

    def is_reducer_ready(self) -> bool:
        """
        Checks whether the reducer of this request is ready to be invoked,
        i.e. if all expected mappers and workers have completed.
        :return: bool True if ready, else False
        """
        request_state = self.dynamo_handler.get_table_item(DynamoTable.STATE_TABLE, self.request_id)

        mappers_complete = (request_state[StateTableField.EXPECTED_MAPPER_EXECUTIONS.value] ==
                            request_state[StateTableField.COMPLETED_MAPPER_EXECUTIONS.value])
        workers_complete = (request_state[StateTableField.EXPECTED_WORKER_EXECUTIONS.value] ==
                            request_state[StateTableField.COMPLETED_WORKER_EXECUTIONS.value])

        return mappers_complete and workers_complete

    def is_request_complete(self) -> bool:
        """
        Checks whether the request has completed,
        i.e. if all expected reducers and converters have completed.
        :return: bool True if complete, else False
        """
        request_state = self.dynamo_handler.get_table_item(DynamoTable.STATE_TABLE, self.request_id)

        reducer_complete = (request_state[StateTableField.EXPECTED_REDUCER_EXECUTIONS.value] ==
                            request_state[StateTableField.COMPLETED_REDUCER_EXECUTIONS.value])
        converter_complete = (request_state[StateTableField.EXPECTED_CONVERTER_EXECUTIONS.value] ==
                              request_state[StateTableField.COMPLETED_CONVERTER_EXECUTIONS.value])

        return reducer_complete and converter_complete

    def log_error(self, message: str):
        """
        Logs the latest error this request reported overwriting the previously logged error.
        :param message: str The error message to log
        """
        logger.debug(message)
        self.dynamo_handler.write_request_error(self.request_id, message)