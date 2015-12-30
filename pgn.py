# Copyright (C) 2013-2014 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import threading
import base64
import chess
import chess.pgn
import datetime
import logging
import requests
from utilities import *
import sys
import os
import re
from email.mime.text import MIMEText


class PgnDisplay(Display, threading.Thread):
    def __init__(self, pgn_file_name, net, email=None, fromINIMailGun_Key=None,
                    fromIniSmtp_Server=None, fromINISmtp_User=None,
                    fromINISmtp_Pass=None, fromINISmtp_Enc=False):
        super(PgnDisplay, self).__init__()
        self.file_name = pgn_file_name
        self.engine_name = ''
        self.old_engine = ''
        self.user_name = ''
        self.location = ''
        self.level = None
        if email and net:  # check if email address is provided by picochess.ini and network traffic is allowed
            self.email = email
        else:
            self.email = False
        # store information for SMTP based mail delivery
        self.smtp_server = fromIniSmtp_Server
        self.smtp_encryption = fromINISmtp_Enc
        self.smtp_user = fromINISmtp_User
        self.smtp_pass = fromINISmtp_Pass
        # store information for mailgun mail delivery
        if email and fromINIMailGun_Key:
            self.mailgun_key = base64.b64decode(str.encode(fromINIMailGun_Key)).decode("utf-8")
        else:
            self.mailgun_key = False

    def run(self):
        while True:
            # Check if we have something to display
            try:
                message = self.message_queue.get()
                if message == Message.SYSTEM_INFO:
                    self.engine_name = message.info['engine_name']
                    self.old_engine = self.engine_name
                    self.user_name = message.info['user_name']
                    self.location = message.info['location']
                if message == Message.LEVEL:
                    self.level = message.level
                if message == Message.INTERACTION_MODE:
                    if message.mode == Mode.REMOTE:
                        self.old_engine = self.engine_name
                        self.engine_name = "Remote Player"
                    else:
                        self.engine_name = self.old_engine
                if message == Message.ENGINE_NAME:
                    self.engine_name = message.ename
                if message == Message.GAME_ENDS and message.game.move_stack:
                    logging.debug('Saving game to [' + self.file_name + ']')
                    pgn = chess.pgn.Game()
                    custom_fen = getattr(message.game, 'custom_fen', None)
                    if custom_fen:
                        pgn.setup(custom_fen)

                    node = pgn
                    for move in message.game.move_stack:
                        node = node.add_main_variation(move)
                    # Headers
                    pgn.headers["Event"] = "PicoChess game"
                    pgn.headers["Site"] = self.location
                    pgn.headers["Date"] = datetime.date.today().strftime('%Y.%m.%d')
                    if message.result == GameResult.ABORT:
                        pgn.headers["Result"] = "*"
                    elif message.result in (GameResult.DRAW, GameResult.STALEMATE, GameResult.SEVENTYFIVE_MOVES,
                                            GameResult.FIVEFOLD_REPETITION, GameResult.INSUFFICIENT_MATERIAL):
                        pgn.headers["Result"] = "1/2-1/2"
                    elif message.result in (GameResult.RESIGN_WHITE, GameResult.RESIGN_BLACK):
                        pgn.headers["Result"] = "1-0" if message.result == GameResult.RESIGN_WHITE else "0-1"
                    elif message.result in (GameResult.MATE, GameResult.OUT_OF_TIME):
                        pgn.headers["Result"] = "0-1" if message.game.turn == chess.WHITE else "1-0"

                    if self.level is None:
                        engine_level = ""
                    else:
                        engine_level = " (Level {0})".format(self.level)

                    if message.play_mode == PlayMode.PLAY_WHITE:
                        pgn.headers["White"] = self.user_name
                        pgn.headers["Black"] = self.engine_name + engine_level
                        pgn.headers["WhiteElo"] = "-"
                        pgn.headers["BlackElo"] = "2900"
                    if message.play_mode == PlayMode.PLAY_BLACK:
                        pgn.headers["White"] = self.engine_name + engine_level
                        pgn.headers["Black"] = self.user_name
                        pgn.headers["WhiteElo"] = "2900"
                        pgn.headers["BlackElo"] = "-"

                    # Save to file
                    file = open(self.file_name, "a")
                    exporter = chess.pgn.FileExporter(file)
                    pgn.accept(exporter)
                    file.flush()
                    file.close()
                    # section send email
                    if self.email:  # check if email adress to send the pgn to is provided
                        if self.smtp_server: # check if smtp server adress provided
                            # if self.smtp_server is not provided than don't try to send email via smtp service
                            logging.debug("SMTP Mail delivery: Started")
                            # change to smtp based mail delivery
                            # depending on encrypted mail delivery, we need to import the right lib
                            if self.smtp_encryption:
                                # lib with ssl encryption
                                logging.debug("SMTP Mail delivery: Import SSL SMTP Lib")
                                from smtplib import SMTP_SSL as SMTP
                            else:
                                # lib without encryption (SMTP-port 21)
                                logging.debug("SMTP Mail delivery: Import standard SMTP Lib (no SSL encryption)")
                                from smtplib import SMTP
                            try:
                                msg = MIMEText(str(pgn), 'plain')  # pack the pgn to Email body
                                msg['Subject'] = "Game PGN"  # put subject to mail
                                msg['From'] = "Your PicoChess computer <no-reply@picochess.org>"
                                logging.debug("SMTP Mail delivery: trying to connect to " + self.smtp_server)
                                conn = SMTP(self.smtp_server)  # contact smtp server
                                conn.set_debuglevel(False)  # no debug info from smtp lib
                                logging.debug("SMTP Mail delivery: trying to log to SMTP Server")
                                logging.debug(
                                    "SMTP Mail delivery: Username=" + self.smtp_user + ", Pass=" + self.smtp_pass)
                                conn.login(self.smtp_user, self.smtp_pass)  # login at smtp server
                                try:
                                    logging.debug("SMTP Mail delivery: trying to send email")
                                    conn.sendmail('no-reply@picochess.org', self.email, msg.as_string())
                                    logging.debug("SMTP Mail delivery: successfuly delivered message to SMTP server")
                                except Exception as exec:
                                    logging.error("SMTP Mail delivery: Failed")
                                    logging.error("SMTP Mail delivery: " + str(exec))
                                finally:
                                    conn.close()
                                    logging.debug("SMTP Mail delivery: Ended")
                            except Exception as exec:
                                logging.error("SMTP Mail delivery: Failed")
                                logging.error("SMTP Mail delivery: " + str(exec))
                        # smtp based system end
                        if self.mailgun_key:  # check if we have the mailgun-key available to send the pgn successful
                            out = requests.post("https://api.mailgun.net/v2/picochess.org/messages",
                                                auth=("api", self.mailgun_key),
                                                data={"from": "Your PicoChess computer <no-reply@picochess.org>",
                                                      "to": self.email,
                                                      "subject": "Game PGN",
                                                      "text": str(pgn)})
                            logging.debug(out)
            except queue.Empty:
                pass
