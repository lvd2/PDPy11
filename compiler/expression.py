from .deferred import Deferred
from .util import octal


class ExpressionEvaluateError(Exception):
	pass

class Expression:
	def __new__(cls, s):
		return Deferred(cls.Get(s), int)

	class Get:
		def __init__(self, s):
			self.s = s

		def __call__(self, compiler):
			if isinstance(self.s, int):
				# Integer
				return self.s
			elif isinstance(self.s, str) and self.s == ".":
				# . (dot)
				return compiler.PC
			else:
				# Label
				def label():
					try:
						return compiler.labels[self.s]
					except KeyError:
						raise ExpressionEvaluateError("Label '{}' not found".format(self.s))

				return Deferred(label, int)

		def deferredRepr(self):
			if isinstance(self.s, int):
				return "Expression({})".format(octal(self.s))
			else:
				return "Expression(@{})".format(self.s)

	@staticmethod
	def asOffset(expr):
		expr.isOffset = True
		return expr