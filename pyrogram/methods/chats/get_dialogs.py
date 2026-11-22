#  Pyrogram - Telegram MTProto API Client Library for Python
#  Copyright (C) 2017-present Dan <https://github.com/delivrance>
#
#  This file is part of Pyrogram.
#
#  Pyrogram is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published
#  by the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Pyrogram is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with Pyrogram.  If not, see <http://www.gnu.org/licenses/>.

from typing import AsyncGenerator, Optional

import pyrogram
from pyrogram import raw, types, utils
from pyrogram.errors import ChannelPrivate, PeerIdInvalid


class GetDialogs:
    async def get_dialogs(
        self: "pyrogram.Client",
        limit: int = 0,
        exclude_pinned: bool | None = None,
        from_archive: bool | None = None,
    ) -> Optional[AsyncGenerator["types.Dialog", None]]:
        """Get a user's dialogs sequentially.

        .. include:: /_includes/usable-by/users.rst

        Parameters:
            limit (``int``, *optional*):
                Limits the number of dialogs to be retrieved.
                By default, no limit is applied and all dialogs are returned.

            exclude_pinned (``bool``, *optional*):
                Exclude pinned dialogs.

            from_archive (``bool``, *optional*):
                Pass True to get dialogs from the archived folder.

        Returns:
            ``Generator``: A generator yielding :obj:`~pyrogram.types.Dialog` objects.

        Example:
            .. code-block:: python

                # Iterate through all dialogs
                async for dialog in app.get_dialogs():
                    print(dialog.chat.first_name or dialog.chat.title)
        """
        current = 0
        total = limit or (1 << 31) - 1
        limit = min(100, total)
        offset_date = 0
        offset_id = 0
        offset_peer = raw.types.InputPeerEmpty()
        seen_dialogs_ids = set()

        while True:
            r = await self.invoke(
                raw.functions.messages.GetDialogs(
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_peer=offset_peer,
                    limit=limit,
                    hash=0,
                    exclude_pinned=exclude_pinned,
                    folder_id=None if from_archive is None else (1 if from_archive else 0),
                ),
                sleep_threshold=60
            )

            users = {i.id: i for i in r.users}
            chats = {i.id: i for i in r.chats}

            messages = {}

            for message in r.messages:
                if isinstance(message, raw.types.MessageEmpty):
                    continue

                chat_id = utils.get_peer_id(message.peer_id)
                try:
                    messages[chat_id] = await types.Message._parse(self, message, users, chats)
                except (ChannelPrivate, PeerIdInvalid):
                    continue

            dialogs = []

            for dialog in r.dialogs:
                if not isinstance(dialog, raw.types.Dialog):
                    continue

                peer_id = utils.get_raw_peer_id(dialog.peer)

                if peer_id in seen_dialogs_ids:
                    continue

                if isinstance(
                    users.get(peer_id) or chats.get(peer_id),
                    (raw.types.UserEmpty, raw.types.ChatEmpty),
                ):
                    continue

                parsed = types.Dialog._parse(self, dialog, messages, users, chats)
                if parsed is None or parsed.chat is None:
                    continue

                seen_dialogs_ids.add(peer_id)
                dialogs.append(parsed)

            if not dialogs:
                return

            last = dialogs[-1]

            last_message = messages.get(last.chat.id) or last.top_message

            if last_message is None:
                return

            offset_id = last_message.id or 0
            date = getattr(last_message, "date", None)
            if isinstance(date, int):
                offset_date = date
            elif date is not None:
                offset_date = utils.datetime_to_timestamp(date)
            else:
                offset_date = 0

            try:
                offset_peer = await self.resolve_peer(last.chat.id)
            except (PeerIdInvalid, KeyError):
                raw_peer = last.raw.peer if getattr(last, "raw", None) else None
                if raw_peer is None:
                    return
                if isinstance(raw_peer, raw.types.PeerUser):
                    offset_peer = raw.types.InputPeerUser(user_id=raw_peer.user_id, access_hash=0)
                elif isinstance(raw_peer, raw.types.PeerChat):
                    offset_peer = raw.types.InputPeerChat(chat_id=raw_peer.chat_id)
                elif isinstance(raw_peer, raw.types.PeerChannel):
                    offset_peer = raw.types.InputPeerChannel(channel_id=raw_peer.channel_id, access_hash=0)
                else:
                    return

            for dialog in dialogs:
                yield dialog

                current += 1

                if current >= total:
                    return
