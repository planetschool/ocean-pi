from gpiozero import CPUTemperature
cpu = CPUTemperature()
import http.server
import socketserver
import datetime
import time
import os
import serial
import board
import csv


i2c_port = 1
lcd_address = 0x27 #present

ser = serial.Serial(
	port="/dev/ttyAMA0",
	baudrate = 9600,
	parity=serial.PARITY_NONE,
	stopbits=serial.STOPBITS_ONE,
	bytesize=serial.EIGHTBITS,
	timeout=3
)

airdirections = []
airspeed1s = []
airspeed5s = []
temperatures = []
rainfall1hs = []
rainfall24hs = []
humiditys = []
barometrics = []

all_data = [airdirections, airspeed1s, airspeed5s, temperatures, rainfall1hs, rainfall24hs, humiditys, barometrics]

knot_conversion = 0.868976

### How to Read the Serial Output
# Example output: c000s000g000t086r000p000h53b10020
# c000 - air direction, degree
# s000 - air speed (1 minute), 0.1 miles per hour
# g000 - air speed (5 minutes), 0.1 miles per hour
# t086 - temperature, Fahrenheit
# r000 - rainfall (1 hour), 0.01 inches
# p000 - rainfall (24 hours), 0.01 inches
# h53 - humidity as percentage
# b10020 - atmospheric pressure, 0.1 hpa 


#### LCD Display
LCD_On = False                                                                                                    
if LCD_On:
	import I2C_LCD_driver
	
	mylcd = I2C_LCD_driver.lcd()
	mylcd.lcd_display_string("Starting up the", 1, 0)
	mylcd.lcd_display_string("Weather Station", 2, 0)

#### Weather Station
Weather_Station_On = True
while Weather_Station_On:
	current_char = ser.read()
	print(current_char)
	print(airdirections)
	# check for equals sign
	if current_char == b'c':
		for lists in all_data:
			lists.clear()
		print(airdirections)
		airdirection = ser.read(4)
		airdirections.append(airdirection.decode('utf-8')[0:3])
		airspeed1 = ser.read(4)
		airspeed1s.append(airspeed1.decode('utf-8')[0:3])
		airspeed5 = ser.read(4)
		airspeed5s.append(airspeed5.decode('utf-8')[0:3])
		temperature = ser.read(4)
		temperatures.append(temperature.decode('utf-8')[0:3])
		rainfall1h = ser.read(4)
		rainfall1hs.append(rainfall1h.decode('utf-8')[0:3])
		rainfall24h = ser.read(4)
		rainfall24hs.append(rainfall24h.decode('utf8')[0:3])
		humidity = ser.read(2)
		humiditys.append(humidity.decode('utf-8')[0:2])
		barometric = ser.read(6)
		barometrics.append(barometric.decode('utf-8')[1:6])

# this part will depend on your specific needs.
# in this example, we stop after 10 readings
# check for stopping condition and set done = True
#	if len(airdirections) >= 1:
#		Weather_Station_On = False
	for airdirection in range(len(airdirections)):
		airdirections[airdirection] = int(airdirections[airdirection])
				
				
	my_adval = ''.join(map(str, airdirections))
	#print("This is the values" + my_adval)
	my_int_ad = int(my_adval)
	my_ad = (my_int_ad)
	print ("Wind Direction:" + '%.2d' % my_ad + " Degrees")
	if my_ad  == 0:
	   my_dir_ad = "North"
	   print (my_dir_ad)
	elif my_ad == 45:
	   my_dir_ad = "North East"
	   print (my_dir_ad)
	elif my_ad == 90:
	   my_dir_ad = "East"
	   print (my_dir_ad)
	elif my_ad == 135:
	   my_dir_ad = "South East"
	   print (my_dir_ad)
	elif my_ad == 180:
	   my_dir_ad = "South"
	   print (my_dir_ad)
	elif my_ad == 225:
	   my_dir_ad = "South West"
	   print (my_dir_ad)
	elif my_ad == 270:
	   my_dir_ad = "West"
	   print (my_dir_ad)
	elif my_ad == 315:
	   my_dir_ad = "North West"
	   print (my_dir_ad)
	else:
	   print ("Something else happened")

	##
	##AirSpeedAvg1###
	for airspeed1 in range(len(airspeed1s)):
		airspeed1s[airspeed1] = int(airspeed1s[airspeed1])
	my_as1val = ''.join(map(str, airspeed1s))
	#print("This is the AS1 value" + my_as1val)
	my_float_as1 = float(my_as1val)
	my_as1_initial = (my_float_as1 * knot_conversion)
	print ("Average Wind Speed(1min):" + '%.1f' % my_as1_initial + "kts")

	###AirSpeedAvg2###
	for airspeed5 in range(len(airspeed5s)):
		airspeed5s[airspeed5] = int(airspeed5s[airspeed5])
	my_as5val = ''.join(map(str, airspeed5s))
	#print("This is the AS5 value" + my_as5val)
	my_float_as2 = float(my_as5val)
	my_as2_initial = (my_float_as2 * knot_conversion)
	print ("Max Wind Speed(5min):" + '%.1f' % my_as2_initial + "kts")

	###Temperature####
	for temperature in range(len(temperatures)):
		temperatures[temperature] = int(temperatures[temperature])
	my_temperatureval = ''.join(map(str, temperatures))
	#print("This is the Temperature value" + my_temperatureval)
	my_float_temp = float(my_temperatureval)
	print ("Temperature:" + '%.1f' % my_float_temp + "F")

	###Rainfall 1H###
	for rainfall1h in range(len(rainfall1hs)):
		rainfall1hs[rainfall1h] = int(rainfall1hs[rainfall1h])
	my_rainfall1hval = ''.join(map(str, rainfall1hs))
	#print("This is the rainfall1h value" + my_rainfall1hval)
	my_float_rf1h = float(my_rainfall1hval)
	my_rf1h = (my_float_rf1h * 0.01)
	print ("Rainfall(1hr):" + '%.1f' % my_rf1h + "in")

	###Rainfall 24H###
	for rainfall24h in range(len(rainfall24hs)):
		rainfall24hs[rainfall24h] = int(rainfall24hs[rainfall24h])
	my_rainfall24hval = ''.join(map(str, rainfall24hs))
	#print("This is the rainfall24h value" + my_rainfall24hval)
	my_float_rf24h = float(my_rainfall24hval)
	my_rf24h = (my_float_rf24h * 0.01)
	print ("Rainfall(24hr):" + '%.1f' % my_rf24h + "in")

	###Humidity###
	for humidity in range(len(humiditys)):
		humiditys[humidity] = int(humiditys[humidity])
	my_humidityval = ''.join(map(str, humiditys))
	my_int_humidity = int(my_humidityval)
	my_humidity = (my_int_humidity)
	print ("Humidity:" + '%.1d' % my_humidity + "%")

	###Barometric Pressure###
	for barometric in range(len(barometrics)):
		barometrics[barometric] = int(barometrics[barometric])
	my_barometricval = ''.join(map(str, barometrics))
	#print("value of barometer:" + my_barometricval)
	my_float_barometric = float(my_barometricval)
	my_barometric_total = (my_float_barometric / 10.00)
	print ("Barometric Pressure:" + '%.1f' % my_barometric_total + "hPa")



if LCD_On:
	mylcd.lcd_clear()
	if Light_Sensor_On:
		mylcd.lcd_clear()
		mylcd.lcd_display_string("Bright: {} Lux".format(lux), 1, 0)
		mylcd.lcd_display_string("IR: {} , Vis: {}".format(IR, visible), 2, 0)
		sleep(2)
	if BME280_Sensor_On:
		mylcd.lcd_clear()
		mylcd.lcd_display_string("Press: {} hPa".format(BME_pressure), 1, 0)
		mylcd.lcd_display_string("Humid: {} %".format(BME_humidity), 2, 0)
		sleep(2)
	if CO2_Sensor_On:
		mylcd.lcd_clear()
		mylcd.lcd_display_string("Temp: {} *F".format(CO2_temp_F), 1, 0)
		mylcd.lcd_display_string("CO2: {} ppm".format(CO2_CO2), 2, 0) 
		sleep(2)
		mylcd.lcd_clear()
		mylcd.lcd_display_string("Humid: {} %".format(CO2_humidity), 1, 0)
		sleep(2)
	if Color_Sensor_On:
		mylcd.lcd_clear()
		mylcd.lcd_display_string("R:" + str(red) + " G:" + str(green) + " B:" + str(blue), 1, 0)
		sleep(2)
		

