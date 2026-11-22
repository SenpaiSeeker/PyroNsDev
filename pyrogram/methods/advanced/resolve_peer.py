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

import logging
import re
from typing import Union

import pyrogram
from pyrogram import enums, raw, utils
from pyrogram.errors import ChannelInvalid, ChannelPrivate, PeerIdInvalid

log = logging.getLogger(__name__)


class ResolvePeer:

    def _resolve_peer_from_message_cache(self, peer_id):
        """Stable fallback from Kurigram: build an InputPeer from a cached message.

        Used when the peer is missing from storage (e.g. a min channel received in
        a dialog list) so pagination/autobcast does not silently stop.
        """
        cache = getattr(self, "message_cache", None)
        if cache is None:
            return None

        items = getattr(cache, "_cache", None)
        if items is None:
            return None

        for (_, _message_id), parsed_message in items.items():
            if not parsed_message:
                continue

            chat = getattr(parsed_message, "chat", None)
            if chat is None or chat.type not in (
                enums.ChatType.GROUP,
                enums.ChatType.SUPERGROUP,
                enums.ChatType.FORUM,
            ):
                continue

            if getattr(chat, "id", None) != peer_id:
                continue

            raw_message = getattr(parsed_message, "raw", None)
            if raw_message is None:
                continue

            sender = parsed_message.from_user or parsed_message.sender_chat
            if sender is None:
                continue

            raw_chat = getattr(chat, "raw", None)
            access_hash = getattr(raw_chat, "access_hash", 0) or 0

            if isinstance(raw_message.peer_id, raw.types.PeerUser):
                return raw.types.InputPeerUser(
                    user_id=utils.get_raw_peer_id(raw_message.peer_id),
                    access_hash=access_hash,
                )
            if isinstance(raw_message.peer_id, raw.types.PeerChat):
                return raw.types.InputPeerChat(chat_id=raw_message.peer_id.chat_id)
            if isinstance(raw_message.peer_id, raw.types.PeerChannel):
                return raw.types.InputPeerChannel(
                    channel_id=utils.get_raw_peer_id(raw_message.peer_id),
                    access_hash=access_hash,
                )

        return None

    async def resolve_peer(
        self: "pyrogram.Client",
        peer_id: Union[int, str]
    ) -> Union[raw.base.InputPeer, raw.base.InputUser, raw.base.InputChannel]:
        """Get the InputPeer of a known peer id.
        Useful whenever an InputPeer type is required.

        .. note::

            This is a utility method intended to be used **only** when working with raw
            :obj:`functions <pyrogram.api.functions>` (i.e: a Telegram API method you wish to use which is not
            available yet in the Client class as an easy-to-use method).

        .. include:: /_includes/usable-by/users-bots.rst

        Parameters:
            peer_id (``int`` | ``str``):
                The peer id you want to extract the InputPeer from.
                Can be a direct id (int), a username (str) or a phone number (str) or *t.me/<username>* link.

        Returns:
            ``InputPeer``: On success, the resolved peer id is returned in form of an InputPeer object.

        Raises:
            KeyError: In case the peer doesn't exist in the internal database.
        """
        if not self.is_connected:
            raise ConnectionError("Client has not been started yet")

        try:
            return await self.storage.get_peer_by_id(peer_id)
        except KeyError:
            if isinstance(peer_id, str):
                if peer_id in ("self", "me"):
                    return raw.types.InputPeerSelf()

                peer_id = re.sub(r"[@+\s]", "", peer_id.lower())
                peer_id = re.sub(r"https://t.me/", "", peer_id.lower())

                try:
                    int(peer_id)
                except ValueError:
                    try:
                        return await self.storage.get_peer_by_username(peer_id)
                    except KeyError:
                        await self.invoke(
                            raw.functions.contacts.ResolveUsername(
                                username=peer_id
                            )
                        )

                        return await self.storage.get_peer_by_username(peer_id)
                else:
                    try:
                        return await self.storage.get_peer_by_phone_number(peer_id)
                    except KeyError:
                        raise PeerIdInvalid

            peer_type = utils.get_peer_type(peer_id)

            if peer_type == "user":
                await self.fetch_peers(
                    await self.invoke(
                        raw.functions.users.GetUsers(
                            id=[
                                raw.types.InputUser(
                                    user_id=peer_id,
                                    access_hash=0
                                )
                            ]
                        )
                    )
                )
            elif peer_type == "chat":
                await self.invoke(
                    raw.functions.messages.GetChats(
                        id=[-peer_id]
                    )
                )
            else:
                try:
                    await self.invoke(
                        raw.functions.channels.GetChannels(
                            id=[
                                raw.types.InputChannel(
                                    channel_id=utils.get_channel_id(peer_id),
                                    access_hash=0
                                )
                            ]
                        )
                    )
                except (ChannelInvalid, ChannelPrivate, PeerIdInvalid):
                    cached = self._resolve_peer_from_message_cache(peer_id)
                    if cached is not None:
                        return cached
                    raise

            try:
                return await self.storage.get_peer_by_id(peer_id)
            except KeyError:
                cached = self._resolve_peer_from_message_cache(peer_id)
                if cached is not None:
                    return cached
                raise PeerIdInvalid
