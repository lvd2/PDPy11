import os
from .parser import Parser, EndOfParsingError
from .deferred import Deferred
from . import commands
from . import util
from .expression import Expression

def octal(n):
	return oct(int(n)).replace("0o", "")

class CompilerError(Exception):
	pass

class Compiler:
	def __init__(self, syntax="py11", link=0o1000, file_list=[], project=None):
		self.syntax = syntax
		self.link_address = link
		self.file_list = file_list
		self.project = project
		self.labels = {}
		self.PC = link
		self.build = []
		self.writes = []

	def addFile(self, file):
		# Resolve file path
		if file.startswith("/") or file[1:3] == ":\\":
			# Absolute
			pass
		else:
			# Relative
			file = os.path.join(os.getcwd(), file)

		with open(file) as f:
			code = f.read()

		self.compileFile(file, code)

	def link(self):
		array = []
		for addr, value in self.writes:
			value = Deferred(value)(self)

			if not isinstance(value, list):
				value = [value]

			for i, value1 in enumerate(value):
				offset = Deferred(addr + i)(self)
				if offset >= len(array):
					array += [0] * (offset - len(array) + 1)
				array[offset] = value1

		self.link_address = Deferred(self.link_address)(self)
		self.output = bytes(array[self.link_address:])
		return self.build

	def compileFile(self, file, code):
		parser = Parser(code, syntax=self.syntax)

		for (command, arg), labels in parser.parse():
			for label in labels:
				if label in self.labels:
					raise CompilerError("Redefinition of label {}".format(label))

				self.labels[label] = self.PC

			if command == ".LINK":
				self.PC = arg
				if self.project is not None:
					self.link_address = arg
			elif command == ".INCLUDE":
				raise NotImplementedError(".INCLUDE and .RAW_INCLUDE are not implemented yet")
			elif command == ".PDP11":
				pass
			elif command == ".I8080":
				raise CompilerError("PY11 cannot compile 8080 programs")
			elif command == ".SYNTAX":
				pass
			elif command == ".BYTE":
				self.writeByte(arg)
			elif command == ".WORD":
				self.writeWord(arg)
			elif command == ".END":
				break
			elif command == ".BLKB":
				bytes_ = Deferred.Repeat(arg, 0)
				self.writeBytes(bytes_)
			elif command == ".BLKW":
				words = Deferred.Repeat(arg, 0)
				self.writeWords(words)
			elif command == ".EVEN":
				self.writeBytes(
					Deferred.If(
						self.PC % 2 == 0,
						[],
						[0]
					)
				)
			elif command == ".ALIGN":
				self.writeBytes(
					Deferred.If(
						self.PC % arg == 0,
						[],
						Deferred.Repeat(
							arg - self.PC % arg,
							0
						)
					)
				)
			elif command == ".ASCII":
				self.writeBytes(
					Deferred(arg)
						.then(lambda string: [ord(char) for char in string])
				)
			elif command == ".MAKE_RAW":
				self.build.append(("raw", arg))
			elif command == ".MAKE_BIN":
				self.build.append(("bin", arg))
			elif command == ".CONVERT1251TOKOI8R":
				pass
			elif command == ".DECIMALNUMBERS":
				pass
			elif command == ".INSERT_FILE":
				with open(arg) as f:
					self.writeBytes([ord(char) for char in f.read()])
			else:
				# It's a simple command
				if command in commands.zero_arg_commands:
					self.writeWord(commands.zero_arg_commands[command])
				elif command in commands.one_arg_commands:
					self.writeWord(
						(commands.one_arg_commands[command] << 6) |
						self.encodeArg(arg[0])
					)
				elif command in commands.jmp_commands:
					offset = arg[0] - self.PC - 2
					offset = (Deferred(offset)
						.then(lambda offset: (
							Deferred.Raise(CompilerError("Unaligned branch: {} bytes".format(octal(offset))))
							if offset % 2 == 1
							else offset
						))
						.then(lambda offset: (
							Deferred.Raise(CompilerError("Too far branch: {} words".format(octal(offset))))
							if offset < -128 or offset > 127
							else offset
						))
					)

					self.writeWord(
						(commands.jmp_commands[command] << 6) |
						util.int8ToUint8(offset)
					)
				elif command in commands.imm_arg_commands:
					max_imm_value = commands.imm_arg_commands[command][1]

					value = (Deferred(arg[0])
						.then(lambda value: (
							Deferred.Raise(CompilerError("Too big immediate value: {}".format(octal(value))))
							if value > max_imm_value
							else value
						))
						.then(lambda value: (
							Deferred.Raise(CompilerError("Negative immediate value: {}".format(octal(value))))
							if value < 0
							else value
						))
					)

					self.writeWord(commands.imm_arg_commands[command][0] | (value // 2))
				elif command in commands.two_arg_commands:
					self.writeWord(
						commands.two_arg_commands[command] |
						(self.encodeArg(arg[0]) << 6) |
						self.encodeArg(arg[1])
					)
				elif command in commands.reg_commands:
					self.writeWord(
						commands.reg_commands[command] |
						(self.encodeRegister(arg[0]) << 6) |
						self.encodeArg(arg[1])
					)
				elif command == "RTS":
					self.writeWord(
						0o000200 | self.encodeRegister(arg[0])
					)
				elif command == "SOB":
					offset = self.PC + 2 - arg[1]
					offset = (Deferred(offset)
						.then(lambda offset: (
							Deferred.Raise(CompilerError("Unaligned SOB: {} bytes".format(octal(offset))))
							if offset % 2 == 1
							else offset
						))
						.then(lambda offset: (
							Deferred.Raise(CompilerError("Too far SOB: {} words".format(octal(offset))))
							if offset < 0 or offset > 63
							else offset
						))
					)

					self.writeWord(
						0o077000 |
						(self.encodeRegister(arg[0]) << 6) |
						(offset // 2)
					)
				else:
					raise CompilerError("Unknown command {}".format(command))

				for arg1 in arg:
					if isinstance(arg1, tuple):
						_, additional = arg1
					elif isinstance(arg1, (int, Expression)):
						additional = arg1
					else:
						additional = None

					if additional is not None:
						self.writeWord(additional)



	def writeByte(self, byte):
		byte = (Deferred(byte)
			.then(lambda byte: (
				Deferred.Raise(CompilerError("Byte {} is too big".format(octal(byte))))
				if byte >= 256 else byte
			))
			.then(lambda byte: (
				Deferred.Raise(CompilerError("Byte {} is too small".format(octal(byte))))
				if byte < -256 else byte
			))
			.then(lambda byte: byte + 256 if byte < 0 else byte)
		)

		self.writes.append((self.PC, byte))
		self.PC = self.PC + 1

	def writeWord(self, word):
		word = (Deferred(word)
			.then(lambda word: (
				Deferred.Raise(CompilerError("Word {} is too big".format(octal(word))))
				if word >= 65536 else word
			))
			.then(lambda word: (
				Deferred.Raise(CompilerError("Word {} is too small".format(octal(word))))
				if word < -65536 else word
			))
			.then(lambda word: word + 65536 if word < 0 else word)
		)

		self.writes.append((self.PC, word & 0xFF))
		self.writes.append((self.PC + 1, word >> 8))
		self.PC = self.PC + 2

	def writeBytes(self, bytes_):
		self.writes.append((self.PC, bytes_))
		self.PC = self.PC + bytes_.then(len)

	def writeWords(self, words):
		self.writes.append((self.PC, words))
		self.PC = self.PC + words.then(len) * 2


	def encodeRegister(self, reg):
		if reg == "SP":
			return 6
		elif reg == "PC":
			return 7
		else:
			return ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7").index(reg)
	def encodeAddr(self, addr):
		return ("Rn", "(Rn)", "(Rn)+", "@(Rn)+", "-(Rn)", "@-(Rn)", "N(Rn)", "@N(Rn)").index(addr)

	def encodeArg(self, arg):
		(reg, addr), _ = arg
		return (self.encodeAddr(addr) << 3) | self.encodeRegister(reg)