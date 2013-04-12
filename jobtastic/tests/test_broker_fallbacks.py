import inspect
import os

import mock
from unittest2 import TestCase


from celery import states
from celery.tests.utils import AppCase, with_eager_tasks
from kombu.exceptions import StdChannelError

USING_CELERY_2_X = False
try:
    from kombu.transport.pyamqp import (
        Transport as AmqpTransport,
        Channel as AmqpChannel,
    )
except ImportError:
    USING_CELERY_2_X = True
    from kombu.transport.amqplib import (
        Transport as AmqpTransport,
        Channel as AmqpChannel,
    )

from jobtastic import JobtasticTask


class ParrotTask(JobtasticTask):
    """
    Just return whatever is passed in as the result.
    """
    significant_kwargs = [
        ('result', str),
    ]
    herd_avoidance_timeout = 0

    def calculate_result(self, result, **kwargs):
        return result


def args_guesser(func):
    # TODO: figure out how to use the inspect module getargspec on classes so
    # we don't need to do this
    for num_args in xrange(5):
        try:
            return func(*['foo' for _ in xrange(num_args)])
        except TypeError:
            pass
    from nose.tools import set_trace; set_trace()
    return func()


class BrokenBrokerTestCase(AppCase):
    if USING_CELERY_2_X:
        connection_errors = [
            IOError,
            OSError,
            AttributeError,
        ]
        channel_errors = [
            StdChannelError,
        ]
    else:
        connection_errors = AmqpTransport(mock.Mock()).connection_errors
        channel_errors = AmqpTransport(mock.Mock()).channel_errors

    def _set_broker_host(self, new_value):
        os.environ['CELERY_BROKER_URL'] = new_value
        self.app.conf.BROKER_URL = new_value
        self.app.conf.BROKER_HOST = new_value

    def setup(self):
        # lowercase on purpose. AppCase calls `self.setup`
        self.app._pool = None
        # Deleting the cache AMQP class so that it gets recreated with the new
        # BROKER_URL
        del self.app.amqp

        self.old_broker_host = self.app.conf.BROKER_HOST

        # Modifying the broken host name simulates the task broker being
        # 'unresponsive'
        # We need to make this modification in 3 places because of version
        # backwards compatibility
        self._set_broker_host('amqp://')
        self.app.conf['BROKER_CONNECTION_RETRY'] = False
        self.app.conf['BROKER_POOL_LIMIT'] = 1
        self.app.conf['CELERY_TASK_PUBLISH_RETRY'] = False

        self.task = ParrotTask()

        # TODO: Figure out how to mock `app.producer_or_acquire` so that we can
        # use a broken `publish_task` to trigger errors.
        # https://github.com/celery/celery/blob/master/celery/app/task.py#L478


        # TODO: use kombu.connection:Connection.transport.connection_errors and
        # kombu.connection:Connection.transport.channel_errors to decide what
        # to catch in the error handler
        # side_effect=self.app.amqp.TaskProducer.connection.channel.channel_errors[0]("Error sending via the channel")

    def teardown(self):
        del self.app.amqp
        self.app._pool = None

        self._set_broker_host(self.old_broker_host)

    @mock.patch.object(
        ParrotTask,
        'calculate_result',
        autospec=True,
        side_effect=AssertionError("Should have skipped calculate_result"),
    )
    def test_delay_or_fail_bad_connection(self, mock_calculate_result):
        # Loop through all of the possible connection errors and ensure they're
        # properly handled
        for error in self.connection_errors:
            with mock.patch.object(
                AmqpChannel,
                'basic_publish',
                autospec=True,
                side_effect=error("Should be handled"),
            ) as mock_basic_publish:
                async_task = self.task.delay_or_fail(result=1)
            self.assertEqual(async_task.status, states.FAILURE)

    @mock.patch.object(
        ParrotTask,
        'calculate_result',
        autospec=True,
        side_effect=AssertionError("Should have skipped calculate_result"),
    )
    def test_delay_or_fail_bad_channel(self, mock_calculate_result):
        transport = AmqpTransport(mock.Mock())
        # Loop through all of the possible channel_errors and ensure they're
        # properly handled
        for error in self.channel_errors:
            with mock.patch.object(
                AmqpChannel,
                'basic_publish',
                autospec=True,
                side_effect=error("Should be handled"),
            ) as mock_basic_publish:
                async_task = self.task.delay_or_fail(result=1)
            self.assertEqual(async_task.status, states.FAILURE)

    def test_delay_or_run_bad_connection(self):
        transport = AmqpTransport(mock.Mock())
        # Loop through all of the possible connection errors and ensure they're
        # properly handled
        for error in self.connection_errors:
            with mock.patch.object(
                AmqpChannel,
                'basic_publish',
                autospec=True,
                side_effect=error("Should be handled"),
            ) as mock_basic_publish:
                async_task, was_fallback = self.task.delay_or_run(result=27)
            self.assertTrue(was_fallback)
            self.assertEqual(async_task, 27)

    def test_delay_or_run_bad_channel(self):
        transport = AmqpTransport(mock.Mock())
        # Loop through all of the possible connection errors and ensure they're
        # properly handled
        for error in self.channel_errors:
            with mock.patch.object(
                AmqpChannel,
                'basic_publish',
                autospec=True,
                side_effect=error("Should be handled"),
            ) as mock_basic_publish:
                async_task, was_fallback = self.task.delay_or_run(result=27)
            self.assertTrue(was_fallback)
            self.assertEqual(async_task, 27)

    def test_delay_or_eager_bad_connection(self):
        transport = AmqpTransport(mock.Mock())
        # Loop through all of the possible connection errors and ensure they're
        # properly handled
        for error in self.connection_errors:
            with mock.patch.object(
                AmqpChannel,
                'basic_publish',
                autospec=True,
                side_effect=error("Should be handled"),
            ) as mock_basic_publish:
                async_task = self.task.delay_or_eager(result=27)
            self.assertEqual(async_task.status, states.SUCCESS)
            self.assertEqual(async_task.result, 27)

    def test_delay_or_eager_bad_channel(self):
        transport = AmqpTransport(mock.Mock())
        # Loop through all of the possible connection errors and ensure they're
        # properly handled
        for error in self.channel_errors:
            with mock.patch.object(
                AmqpChannel,
                'basic_publish',
                autospec=True,
                side_effect=error("Should be handled"),
            ) as mock_basic_publish:
                async_task = self.task.delay_or_eager(result=27)
            self.assertEqual(async_task.status, states.SUCCESS)
            self.assertEqual(async_task.result, 27)


class WorkingBrokerTestCase(AppCase):
    def setup(self):
        self.task = ParrotTask()

    @with_eager_tasks
    def test_sanity(self):
        # The task actually runs
        async_task = self.task.delay(result=1)
        self.assertEqual(async_task.status, states.SUCCESS)
        self.assertEqual(async_task.result, 1)

    @with_eager_tasks
    @mock.patch.object(
        ParrotTask,
        'calculate_result',
        autospec=True,
        return_value=1,
    )
    def test_delay_or_fail_runs(self, mock_calculate_result):
        async_task = self.task.delay_or_fail(result=1)
        self.assertEqual(async_task.status, states.SUCCESS)
        self.assertEqual(async_task.result, 1)

        self.assertEqual(mock_calculate_result.call_count, 1)

    @with_eager_tasks
    @mock.patch.object(
        ParrotTask,
        'calculate_result',
        autospec=True,
        return_value=1,
    )
    def test_delay_or_run_runs(self, mock_calculate_result):
        async_task, _ = self.task.delay_or_run(result=1)
        self.assertEqual(async_task.status, states.SUCCESS)
        self.assertEqual(async_task.result, 1)

        self.assertEqual(mock_calculate_result.call_count, 1)

    @with_eager_tasks
    @mock.patch.object(
        ParrotTask,
        'calculate_result',
        autospec=True,
        return_value=1,
    )
    def test_delay_or_eager_runs(self, mock_calculate_result):
        async_task = self.task.delay_or_eager(result=1)
        self.assertEqual(async_task.status, states.SUCCESS)
        self.assertEqual(async_task.result, 1)

        self.assertEqual(mock_calculate_result.call_count, 1)
