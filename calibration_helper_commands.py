def send(cmd):
	bus.write_i2c_block_data(addr, 0x00, [ord(c) for c in cmd])
	time.sleep(1.5)
	
def read():
	data = bus.read_i2c_block_data(addr, 0x00, 32)
	print("raw:", data)
	print("code:", data[0])
	print("text:", ''.join(chr(x) for x in data[1:] if x != 0))

def send(cmd):
	bus.write_i2c_block_data(addr, 0x00, [ord(c) for c in cmd])
	time.sleep(2)
	data = bus.read_i2c_block_data(addr, 0x00, 32)
	print("raw:", data)
	print("code:", data[0])
	print("text:", ''.join(chr(x) for x in data[1:] if x != 0))
	
# Above commands are drafts. Below commands are tested and work.
# For running calibration in Terminal, start a Python session and type the following commands.
# Refer to Atlas documentation for command syntax. The most common are "R", "I", and "Cal,..." with some known calibration value added after "Cal"

from smbus2 import SMBus, i2c_msg
import time

bus = SMBus(1)
addr = 0x64

def send(cmd):
	msg = i2c_msg.write(addr, cmd.encode("ascii"))
	bus.i2c_rdwr(msg)
	time.sleep(2)
	data = bus.read_i2c_block_data(addr, 0x00, 32)
	print("raw:", data)
	print("code:", data[0])
	print("text:", ''.join(chr(x) for x in data[1:] if x != 0))
	
