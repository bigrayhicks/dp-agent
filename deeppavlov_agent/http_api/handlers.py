import asyncio
from datetime import datetime
from string import hexdigits
from time import time

import aiohttp_jinja2
from aiohttp import web

from ..state_formatters.output_formatters import (http_api_output_formatter,
                                                  http_debug_output_formatter)


class ApiHandler:
    def __init__(self, debug=False, response_time_limit=5):
        self.debug = debug
        self.response_time_limit = response_time_limit

    async def handle_api_request(self, request):
        async def handle_command(payload, user_id, state_manager):
            if payload in {'/start', '/close'} and state_manager:
                await state_manager.drop_active_dialog(user_id)
                return True

        response = {}
        register_msg = request.app['agent'].register_msg
        if request.method == 'POST':
            if 'content-type' not in request.headers \
                    or not request.headers['content-type'].startswith('application/json'):
                raise web.HTTPBadRequest(reason='Content-Type should be application/json')
            data = await request.json()

            user_id = data.pop('user_id')
            payload = data.pop('payload', '')

            deadline_timestamp = None
            if self.response_time_limit:
                deadline_timestamp = time() + self.response_time_limit

            if not user_id:
                raise web.HTTPBadRequest(reason='user_id key is required')

            command_performed = await handle_command(payload, user_id, request.app['agent'].state_manager)
            if command_performed:
                return web.json_response({})

            response = await asyncio.shield(
                register_msg(utterance=payload, user_telegram_id=user_id,
                             user_device_type=data.pop('user_device_type', 'http'),
                             date_time=datetime.now(),
                             location=data.pop('location', ''),
                             channel_type='http_client',
                             message_attrs=data, require_response=True,
                             deadline_timestamp=deadline_timestamp)
            )

            if response is None:
                raise RuntimeError('Got None instead of a bot response.')
            if self.debug:
                return web.json_response(http_debug_output_formatter(response['dialog'].to_dict()))
            else:
                return web.json_response(http_api_output_formatter(response['dialog'].to_dict()))

    async def dialog(self, request):
        state_manager = request.app['agent'].state_manager
        dialog_id = request.match_info['dialog_id']
        if len(dialog_id) == 24 and all(c in hexdigits for c in dialog_id):
            dialog_obj = await state_manager.get_dialog_by_id(dialog_id)
            if not dialog_obj:
                raise web.HTTPNotFound(reason=f'dialog with id {dialog_id} does not exist')
            return web.json_response(dialog_obj.to_dict())
        raise web.HTTPBadRequest(reason='dialog id should be 24-character hex string')

    async def dialogs_by_user(self, request):
        state_manager = request.app['agent'].state_manager
        user_telegram_id = request.match_info['user_telegram_id']
        dialogs = await state_manager.get_dialogs_by_user_ext_id(user_telegram_id)
        return web.json_response([i.to_dict() for i in dialogs])


class PagesHandler:
    def __init__(self, debug=False):
        self.debug = debug

    async def ping(self, request):
        return web.json_response("pong")


class WSstatsHandler:
    def __init__(self):
        self.update_time = 0.5

    @aiohttp_jinja2.template('services_ws_highcharts.html')
    async def ws_page(self, request):
        return {}

    async def index(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        request.app['websockets'].append(ws)
        logger_stats = request.app['logger_stats']
        while True:
            data = dict(logger_stats.get_current_load())
            await ws.send_json(data)
            await asyncio.sleep(self.update_time)

        return ws
