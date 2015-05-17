#!/usr/bin/python3

# Netbeeper par Linuxomaniac est très fortement inspiré de « MIDI Beeper (c) 2007-2010 Silas S. Brown. License: GPL. »
# Netbeeper est sous licence GPL v3

from math import pow
from select import select
from socket import socket, AF_INET, SOCK_STREAM
from sys import argv
from struct import pack, unpack

min_pulseLength, max_pulseLength = 10, 20 # Milliseconds
DEFAULT_PORT = 4242

# Liste des événements midi utilisés
NOTE_OFF = 0x80
NOTE_ON = 0x90
AFTERTOUCH = 0xA0
CONTINUOUS_CONTROLLER = 0xB0
PATCH_CHANGE = 0xC0
CHANNEL_PRESSURE = 0xD0
PITCH_BEND = 0xE0
SYSTEM_EXCLUSIVE = 0xF0
MTC = 0xF1
SONG_POSITION_POINTER = 0xF2
SONG_SELECT = 0xF3
TUNING_REQUEST = 0xF6
END_OFF_EXCLUSIVE = 0xF7
SEQUENCE_NUMBER = 0x00
TEXT = 0x01
COPYRIGHT = 0x02
SEQUENCE_NAME = 0x03
INSTRUMENT_NAME = 0x04
LYRIC = 0x05
MARKER = 0x06
CUEPOINT = 0x07
PROGRAM_NAME = 0x08
DEVICE_NAME = 0x09
MIDI_CH_PREFIX = 0x20
MIDI_PORT = 0x21
END_OF_TRACK = 0x2F
TEMPO = 0x51
SMTP_OFFSET = 0x54
TIME_SIGNATURE = 0x58
KEY_SIGNATURE = 0x59
META_EVENT = 0xFF

PAQUET_AREUREADY = 1
PAQUET_OKREADY= 2
PAQUET_NOTE = 3
PAQUET_EOF = 4
PAQUET_START = 5
PAQUET_OKSTART = 6
PAQUET_FINISHED = 7

midi_note_to_freq = []
for i in range(128): midi_note_to_freq.append((440 / 32.0) * pow(2, (len(midi_note_to_freq) - 9) / 12.0))
def to_freq(n):
	if n == int(n):
		try: return midi_note_to_freq[int(n)]
		except: return 0
	else: return (440 / 32.0) * pow(2, (n-9) / 12.0)

def add_midi_note_chord(noteNos, microsecs):# Wow ! J'ai bien galéré à tout réécrire pour que ce soit sous la forme [freq, length, delay], parce qu'avant delay était une note supplémentaire de la forme : [0, 0, delay]
	global current_chord
	global cumulative_params
	millisecs = microsecs / 1000
	noteNos.sort()
	if noteNos == current_chord[0]: # It's just an extention of the existing one
		current_chord[1] += millisecs
		return
	else:
		if not current_chord[0]:
			try: cumulative_params[-1][2] = round(current_chord[1])# On remplace le dernier élément par un temps d'attente
			except: cumulative_params.append([0, 0, round(current_chord[1])])
		elif len(current_chord[0]) == 1: cumulative_params.append([round(to_freq(current_chord[0][0])), round(current_chord[1]), 0])
		else:
			pulseLength = max(min(current_chord[1] / len(current_chord[0]), max_pulseLength), min_pulseLength)
			cumulative_params.extend([[round(to_freq(x)), round(pulseLength), 0] for x in current_chord[0]] * round(max(1, current_chord[1] / pulseLength / len(current_chord[0]))))

		current_chord = [noteNos, millisecs]

# Some of the code below is taken from Python Midi Package by Max M,
# http://www.mxm.dk/products/public/pythonmidi
# with much cutting-down and modifying
# Yes, such very très le much
def readBew(value):
	return unpack('>%s' % {1:'B', 2:'H', 4:'L'}[len(value)], value)[0]

def readVar(value):
	sum = 0
	for byte in unpack('%sB' % len(value), value):
		sum = (sum << 7) + (byte & 0x7F)
		if not 0x80 & byte: break
	return sum

def varLen(value):
	if value <= 127: return 1
	elif value <= 16383: return 2
	elif value <= 2097151: return 3
	else: return 4

def toBytes(value):
	return unpack('%sB' % len(value), value)

class MidiToBeep:
	def update_time(self, new_time=0):
		self._relative_time = new_time
		if self._relative_time:
			# time was advanced, so output something
			d = {}
			for c,v in self.current_notes_on: d[v + self.semitonesAdd[c]] = 1
			if self.need_to_interleave_tracks: self.tracks[-1].append([d.keys(), self._relative_time * self.microsecsPerDivision])
			else: add_midi_note_chord(list(d.keys()), self._relative_time * self.microsecsPerDivision)
	def reset_time(self): self._relative_time = 0
	def set_current_track(self, new_track): self._current_track = new_track
	def __init__(self):
		self._relative_time = 0
		self._current_track = 0
		self._running_status = None
		self.current_notes_on = []
		self.rpnLsb = [0]*16
		self.rpnMsb = [0]*16
		self.semitoneRange = [1]*16
		self.semitonesAdd = [0]*16
		self.microsecsPerDivision = 10000
	def note_on(self, channel=0, note=0x40, velocity=0x40):
		if velocity: self.current_notes_on.append((channel,note))# and not channel==9
	def note_off(self, channel=0, note=0x40, velocity=0x40):
		try: self.current_notes_on.remove((channel,note))
		except ValueError: pass
	def aftertouch(self, channel=0, note=0x40, velocity=0x40): pass
	def continuous_controller(self, channel, controller, value):
		# Interpret "pitch bend range":
		if controller==64: self.rpnLsb[channel] = value
		elif controller==65: self.rpnMsb[channel] = value
		elif controller==6 and self.rpnLsb[channel]==self.rpnMsb[channel]==0:
			self.semitoneRange[channel]=value
	def patch_change(self, channel, patch): pass
	def channel_pressure(self, channel, pressure): pass
	def pitch_bend(self, channel, value):
		# Pitch bend is sometimes used for slurs so we'd better interpret it (only MSB for now; full range is over 8192)
		self.semitonesAdd[channel] = (value - 64) * self.semitoneRange[channel]/64.0
	def sysex_event(self, data): pass
	def midi_time_code(self, msg_type, values): pass
	def song_position_pointer(self, value): pass
	def song_select(self, songNumber): pass
	def tuning_request(self): pass
	def header(self, format=0, nTracks=1, division=96):
		self.division=division
		self.need_to_interleave_tracks = (format==1)
		self.tracks = [[]]
	def eof(self):
		if self.need_to_interleave_tracks:
			while True: # delete empty tracks
				try: self.tracks.remove([])
				except ValueError: break
			while self.tracks:
				minLen = min([t[0][1] for t in self.tracks])
				d = {}
				for t in self.tracks: d.update([(n,1) for n in t[0][0]])
				add_midi_note_chord(list(d.keys()), minLen)
				for t in self.tracks:
					t[0][1] -= minLen
					if t[0][1]==0: del t[0]
				while True: # delete empty tracks
					try: self.tracks.remove([])
					except ValueError: break
	def meta_event(self, meta_type, data): pass
	def start_of_track(self, n_track=0):
		self.reset_time()
		self._current_track += 1
		if self.need_to_interleave_tracks: self.tracks.append([])
	def end_of_track(self): pass
	def sequence_number(self, value): pass
	def text(self, text): pass
	def copyright(self, text): pass
	def sequence_name(self, text): pass
	def instrument_name(self, text): pass
	def lyric(self, text): pass
	def marker(self, text): pass
	def cuepoint(self, text): pass
	def program_name(self,progname): pass
	def device_name(self,devicename): pass
	def midi_ch_prefix(self, channel): pass
	def midi_port(self, value): pass
	def tempo(self, value):
		# TODO if need_to_interleave_tracks, and tempo is not already put in on all tracks, and there's a tempo command that's not at the start and/or not on 1st track, we may need to do something
		self.microsecsPerDivision = value/self.division
	def smtp_offset(self, hour, minute, second, frame, framePart): pass
	def time_signature(self, nn, dd, cc, bb): pass
	def key_signature(self, sf, mi): pass

class RawInstreamFile:
	def __init__(self, infile=''):
		if infile:
				infile = open(infile, 'rb')
				self.data = infile.read()
				infile.close()
		else: self.data = ''
		self.cursor = 0
	def getCursor(self): return self.cursor
	def moveCursor(self, relative_position=0): self.cursor += relative_position
	def nextSlice(self, length, move_cursor=1):
		c = self.cursor
		slc = self.data[c:c+length]
		if move_cursor:
			self.moveCursor(length)
		return slc
	def readBew(self, n_bytes=1, move_cursor=1): return readBew(self.nextSlice(n_bytes, move_cursor))
	def readVarLen(self):
		MAX_VARLEN = 4
		var = readVar(self.nextSlice(MAX_VARLEN, 0))
		self.moveCursor(varLen(var))
		return var

class EventDispatcher:
	def __init__(self, outstream):
		self.outstream = outstream
		self.convert_zero_velocity = 1
		self.dispatch_continuos_controllers = 1
		self.dispatch_meta_events = 1
	def header(self, format, nTracks, division): self.outstream.header(format, nTracks, division)
	def start_of_track(self, current_track):
		self.outstream.set_current_track(current_track)
		self.outstream.start_of_track(current_track)
	def sysex_event(self, data): self.outstream.sysex_event(data)
	def eof(self): self.outstream.eof()
	def update_time(self, new_time=0): self.outstream.update_time(new_time)
	def reset_time(self): self.outstream.reset_time()
	def channel_messages(self, hi_nible, channel, data):
		stream = self.outstream
		data = toBytes(data)
		if (NOTE_ON & 0xF0) == hi_nible:
			note, velocity = data
			if velocity==0 and self.convert_zero_velocity: stream.note_off(channel, note, 0x40)
			else: stream.note_on(channel, note, velocity)
		elif (NOTE_OFF & 0xF0) == hi_nible:
			note, velocity = data
			stream.note_off(channel, note, velocity)
		elif (AFTERTOUCH & 0xF0) == hi_nible:
			note, velocity = data
			stream.aftertouch(channel, note, velocity)
		elif (CONTINUOUS_CONTROLLER & 0xF0) == hi_nible:
			controller, value = data
			if self.dispatch_continuos_controllers: self.continuous_controllers(channel, controller, value)
			else: stream.continuous_controller(channel, controller, value)
		elif (PATCH_CHANGE & 0xF0) == hi_nible:
			program = data[0]
			stream.patch_change(channel, program)
		elif (CHANNEL_PRESSURE & 0xF0) == hi_nible:
			pressure = data[0]
			stream.channel_pressure(channel, pressure)
		elif (PITCH_BEND & 0xF0) == hi_nible:
			hibyte, lobyte = data
			value = (hibyte<<7) + lobyte
			stream.pitch_bend(channel, value)
		else:
			raise ValueError("Illegal channel message!")
	def continuous_controllers(self, channel, controller, value):
		stream = self.outstream
		stream.continuous_controller(channel, controller, value)
	def system_commons(self, common_type, common_data):
		stream = self.outstream
		if common_type == MTC:
			data = readBew(common_data)
			msg_type = (data & 0x07) >> 4
			values = (data & 0x0F)
			stream.midi_time_code(msg_type, values)
		elif common_type == SONG_POSITION_POINTER:
			hibyte, lobyte = toBytes(common_data)
			value = (hibyte<<7) + lobyte
			stream.song_position_pointer(value)
		elif common_type == SONG_SELECT:
			data = readBew(common_data)
			stream.song_select(data)
		elif common_type == TUNING_REQUEST:
			stream.tuning_request(time=None)
	def meta_events(self, meta_type, data):
		stream = self.outstream
		if meta_type == SEQUENCE_NUMBER:
			number = readBew(data)
			stream.sequence_number(number)
		elif meta_type == TEXT:
			stream.text(data)
		elif meta_type == COPYRIGHT:
			stream.copyright(data)
		elif meta_type == SEQUENCE_NAME:
			stream.sequence_name(data)
		elif meta_type == INSTRUMENT_NAME:
			stream.instrument_name(data)
		elif meta_type == LYRIC:
			stream.lyric(data)
		elif meta_type == MARKER:
			stream.marker(data)
		elif meta_type == CUEPOINT:
			stream.cuepoint(data)
		elif meta_type == PROGRAM_NAME:
			stream.program_name(data)
		elif meta_type == DEVICE_NAME:
			stream.device_name(data)
		elif meta_type == MIDI_CH_PREFIX:
			channel = readBew(data)
			stream.midi_ch_prefix(channel)
		elif meta_type == MIDI_PORT:
			port = readBew(data)
			stream.midi_port(port)
		elif meta_type == END_OF_TRACK:
			stream.end_of_track()
		elif meta_type == TEMPO:
			b1, b2, b3 = toBytes(data)
			stream.tempo((b1<<16) + (b2<<8) + b3)
		elif meta_type == SMTP_OFFSET:
			hour, minute, second, frame, framePart = toBytes(data)
			stream.smtp_offset(hour, minute, second, frame, framePart)
		elif meta_type == TIME_SIGNATURE:
			nn, dd, cc, bb = toBytes(data)
			stream.time_signature(nn, dd, cc, bb)
		elif meta_type == KEY_SIGNATURE:
			sf, mi = toBytes(data)
			stream.key_signature(sf, mi)
		else:
			meta_data = toBytes(data)
			stream.meta_event(meta_type, meta_data)

class MidiFileParser:
	def __init__(self, raw_in, outstream):
		self.raw_in = raw_in
		self.dispatch = EventDispatcher(outstream)
		self._running_status = None
	def parseMThdChunk(self):
		raw_in = self.raw_in
		header_chunk_type = raw_in.nextSlice(4)
		header_chunk_zise = raw_in.readBew(4)
		if header_chunk_type.decode() != 'MThd': raise TypeError("This is not a valid midi file!")
		self.format = raw_in.readBew(2)
		self.nTracks = raw_in.readBew(2)
		self.division = raw_in.readBew(2)
		if header_chunk_zise > 6:
			raw_in.moveCursor(header_chunk_zise-6)
		self.dispatch.header(self.format, self.nTracks, self.division)
	def parseMTrkChunk(self):
		self.dispatch.reset_time()
		dispatch = self.dispatch
		raw_in = self.raw_in
		dispatch.start_of_track(self._current_track)
		raw_in.moveCursor(4)
		tracklength = raw_in.readBew(4)
		track_endposition = raw_in.getCursor() + tracklength
		while raw_in.getCursor() < track_endposition:
			time = raw_in.readVarLen()
			dispatch.update_time(time)
			peak_ahead = raw_in.readBew(move_cursor=0)
			if (peak_ahead & 0x80): status = self._running_status = raw_in.readBew()
			else: status = self._running_status
			hi_nible, lo_nible = status & 0xF0, status & 0x0F
			if status == META_EVENT:
				meta_type = raw_in.readBew()
				meta_length = raw_in.readVarLen()
				meta_data = raw_in.nextSlice(meta_length)
				dispatch.meta_events(meta_type, meta_data)
			elif status == SYSTEM_EXCLUSIVE:
				sysex_length = raw_in.readVarLen()
				sysex_data = raw_in.nextSlice(sysex_length-1)
				if raw_in.readBew(move_cursor=0) == END_OFF_EXCLUSIVE: eo_sysex = raw_in.readBew()
				dispatch.sysex_event(sysex_data)
			elif hi_nible == 0xF0:
				data_sizes = {
					MTC:1,
					SONG_POSITION_POINTER:2,
					SONG_SELECT:1
				}
				data_size = data_sizes.get(hi_nible, 0)
				common_data = raw_in.nextSlice(data_size)
				common_type = lo_nible
				dispatch.system_common(common_type, common_data)
			else:
				data_sizes = {
					PATCH_CHANGE:1,
					CHANNEL_PRESSURE:1,
					NOTE_OFF:2,
					NOTE_ON:2,
					AFTERTOUCH:2,
					CONTINUOUS_CONTROLLER:2,
					PITCH_BEND:2
				}
				data_size = data_sizes.get(hi_nible, 0)
				channel_data = raw_in.nextSlice(data_size)
				event_type, channel = hi_nible, lo_nible
				dispatch.channel_messages(event_type, channel, channel_data)

def create_paquet(status, data1, data2, data3):
	return pack("BIII", status, data1, data2, data3)

def extract_paquet(p):
	return unpack("BIII", p)

print("Netbeeper par Linuxomaniac. Inspiré par : MIDI Beeper")

if len(argv) < 3:
	print("Utilisation : %s <Fichier MIDI> <IP[:Port][:Piste]> [...]" % (argv[0]))
	exit(1)

# On parse les hosts en argument
hosts = []
for i in argv[2:]:# On lit tous les arguments pour les traiter
	i = i.split(':')
	if len(i) == 1: i.append(DEFAULT_PORT)# S'il n'y a pas de port, on ajoute le port par défaut
	if len(i) > 2: i[2] = int(i[2])
	i[1] = int(i[1])# Convertir l'argument en int (oui, c'est dégueu)
	hosts.append(i)

# On parse le fichier
print("Analyse syntaxique du fichier %s..." % argv[1])
parser = MidiFileParser(RawInstreamFile(argv[1]), MidiToBeep())
parser.parseMThdChunk()
params_list = []
params_index = 0
for t in range(parser.nTracks):
	# Global très sale
	cumulative_params = []
	current_chord = [[], 0]

	parser._current_track = t
	parser.parseMTrkChunk()
	parser.dispatch.eof()
	add_midi_note_chord([], 0)# Ensure flushed

	if cumulative_params:
		params_list.append(cumulative_params)
		params_index += 1# On utilise ça, car c'est surement plus rapide que len(params_list)

del parser

print("Wow ! %d pistes dans le fichier et %d hôte(s) défini(s) !" % (params_index, len(hosts)))

track_counter = 0
socks = []
socks2 = []
for host in hosts:
	if len(host) == 2:
		host.append(track_counter)# Si on n'a pas entré de numéro manuellement, on met donc le numéro de piste sur le compteur
		track_counter += 1# On incrémente que si on se sert du numéro fourni par le compteur
	elif host[2] >= params_index:
		raise ValueError('Numéro fourni en argument plus grand que le nombre de pistes du fichier pour %s !' % (host[0]))

	params = params_list[host[2] % params_index]# Nom plus facile

	print("Envoi de la piste %d à %s:%d... " % (host[2], host[0], host[1]))

	# Toute la sauce avec les sockets
	sock = socket(AF_INET, SOCK_STREAM)
	sock.connect((host[0], host[1]))

	print("Tentative de connexion avec %s..." % host[0])
	sock.send(create_paquet(PAQUET_AREUREADY, 0, 0, 0))# Pour que le programme prépare son anus
	if extract_paquet(sock.recv(16)) != (PAQUET_OKREADY, 0, 0, 0):# 13 pour 3 * 4 + 1, mais unpack se plaint alors 16 ça passe, comme il le préconise lui-même
		print("Mauvaise réponse de la part de %s !" % host[0])
		exit(1)

	print("Réponse positive ! Envoi des données...")
	for param in params:
		if param[0] != 0 or param[1] != 0 or param[2] != 0:
			sock.send(create_paquet(PAQUET_NOTE, param[0], param[1], param[2]))# On transmet les trois Unsigned Int en bytes (fréquence, durée de la note, délai après la note)
	sock.send(create_paquet(PAQUET_EOF, 0, 0, 0))

	if extract_paquet(sock.recv(16)) != (PAQUET_START, 0, 0, 0):
		print("%s n'est pas content !" % host[0])
		exit(1)

	print("Terminé, %s prêt pour la bagarre !" % host[0])
	sock.send(create_paquet(PAQUET_OKSTART, 0, 0, 0))# Nous aussi on est prêt, mec

	socks.append(sock)

	sock2 = socket(AF_INET, SOCK_STREAM)
	sock2.connect((host[0], host[1]))
	socks2.append(sock2)

print("\nOn envoie le signal à tout le monde...")
for sock in socks2:# On lance tout en même temps, car si le parsage met du temps, on ne veut pas de décalage
	sock.close()

print("En attente de la fin de la musique...")
while True:
	res = select(socks, [], [], 1)# On vérifie si un socket a terminé, toutes les secondes
	if res[0]:
		for sock in res[0]:# On traite tous les sockets qui ont reçu des données, c'est-à-dire une connexion fermée
			if extract_paquet(sock.recv(16)) != (PAQUET_FINISHED, 0, 0, 0):
				print("Quoi ? On a reçu des données qui ne correspondent pas à une fermeture de connexion !?")
			sock.close()# On les ferme
			socks.remove(sock)# On les vire de la liste des sockets à tester
	if len(socks) == 0: break# Il ne reste plus de sockets
