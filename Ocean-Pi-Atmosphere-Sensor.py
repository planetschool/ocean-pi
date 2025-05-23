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

'''
All packages for the sensors are installed in a Virtual Environment. You can create a Virtual Environment by running "python -m venv venv-ocean-pi"
in the home directory (/planetschool, on our pi)

To activate, run 'source venv-ocean-pi/bin/activate'

The following sensor packages are required to be installed inside the Virtual Environment (venv-ocean-pi) before running this program:
pip3 install adafruit-circuitpython-scd4x
pip3 install adafruit-circuitpython-tsl2591
pip3 install adafruit-circuitpython-ltr390
pip3 install adafruit-circuitpython-bmp3xx
pip3 install adafruit-circuitpython-sgp40
pip3 install adafruit-circuitpython-lis2mdl
pip3 install adafruit-circuitpython-lsm303-accel
pip3 install adafruit-circuitpython-veml7700
'''

i2c_port = 1
tcs34725_RGB_address = 0x29 #present
bme280_temp_pres_hum_address = 0x77 #present? or bmp388?
scd41_co2_address = 0x62 #present
lcd_address = 0x27 #present
tsl2590_light_address = 0x29 #present
ltr390_lightUV_address = 0x53 #present
veml7700_light_address = 0x10 #present
lsm303agr_accel_magnet_address = 0x19 + 0x1e #present and unsure of why two addresses
bmp388_precision_alt_temp_pres_address = 0x77 #present? or bme280?
sgp40_mox_gas_address = 0x59 #present but does not show in i2cdetect for some reason

sleep = time.sleep


#### LCD Display
LCD_On = True                                                                                                       
if LCD_On:
	import I2C_LCD_driver
	
	mylcd = I2C_LCD_driver.lcd()
	mylcd.lcd_display_string("Starting up the", 1, 0)
	mylcd.lcd_display_string("Weather Station", 2, 0)


#### Non-Weather Station Sensors

i2c = board.I2C()
Sensor_Interval = 5		# Number of seconds between polling the sensor array
data_header = ["Month", "Day", "Year", "Hour", "Minute", "Second"]

### Mox Gas Sensor
import adafruit_sgp40
sgp = adafruit_sgp40.SGP40(i2c, int(sgp40_mox_gas_address))
print("Raw gas: ", sgp.raw)


### Color Sensor TCS34725
#In the terminal, run 'sudo pip3 install adafruit-circuitpython-tcs34725 --break-system-packages'
Color_Sensor_On = False

if Color_Sensor_On:
	import adafruit_tcs34725
	light_sensor = adafruit_tcs34725.TCS34725(i2c, int(tcs34725_RGB_address))
	#print(light_sensor.color_rgb_bytes)
	data_header.extend(["Red Light", "Green Light", "Blue Light"])
	

### BME280 Temp, Pressure, Humidity
#In the terminal run 'sudo pip3 install adafruit-circuitpython-bme280 --break-system-packages'
BME280_Sensor_On = False

if BME280_Sensor_On:
	from adafruit_bme280 import basic as adafruit_bme280
	import smbus2
	bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c)
	BME_humidity = bme280.humidity
	BME_pressure = bme280.pressure
	BME_temp = bme280.temperature
	data_header.extend(["BME Temperature (*F)", "BME Humidity (%)", "BME Pressure (hPa)"])
	#print("Temp: {}, Pressure: {}, Humidity: {}".format(BME_temp, BME_pressure, BME_humidity))


### BMP388 Temp, Pressure, Altitude
BMP388_Sensor_On = True
#uses i2c address 0x77, so cannot be attached to the same pi as BME280

if BMP388_Sensor_On:
	import adafruit_bmp3xx
	bmp = adafruit_bmp3xx.BMP3XX_I2C(i2c)
	bmp.sea_level_pressure = 1013.25 #Need to establish sea level pressure in order to extrapolate altitude. Fun project opportunity here.
	bmp.pressure_oversampling = 8
	bmp.temperature_oversampling = 2
	

### CO2 Sensor
#In the terminal, run 'sudo pip3 install adafruit-circuitpython-scd4x --break-system-packages'
#If using a venv (virtual environment), run 'pip3 install adafruit-circuitpython-scd4x'
CO2_Sensor_On = True

if CO2_Sensor_On:
	import adafruit_scd4x as CO2
	CO2_sensor = CO2.SCD4X(i2c, int(scd41_co2_address))
	CO2_sensor.start_periodic_measurement()
	print("Waiting for first measurement...")
	data_header.extend(["CO2 Temperature (*F)", "CO2 Humidity (%)", "CO2 PPM"])
	

### TSL2591 Light Sensor
#In the terminal, run 'sudo pip3 install adafruit-circuitpython-tsl2591 --break-system-packages'
Light_Sensor_On = True

if Light_Sensor_On:
	import adafruit_tsl2591 as Light
	Light_sensor = Light.TSL2591(i2c, int(tsl2590_light_address))
	lux = Light_sensor.lux
	visible = Light_sensor.visible		
	IR = Light_sensor.infrared
	data_header.extend(["Brightness (lux)", "Visible Light", "Infrared Light"])
	#print("Brightness: {}, Visible Light: {}, Infrared Light: {}".format(lux, visible, IR))


### LSM303 Accelerometer and Magnetometer 
Accel_Sensor_On = True

if Accel_Sensor_On:
	import adafruit_lsm303_accel
	import adafruit_lis2mdl
	accel = adafruit_lsm303_accel.LSM303_Accel(i2c)
	mag = adafruit_lis2mdl.LIS2MDL(i2c)


### LTR390 UV Sensor
UV_Sensor_On = True

if UV_Sensor_On:
	import adafruit_ltr390
	ltr = adafruit_ltr390.LTR390(i2c)


### VEML7700 Ambient Light Sensor
Ambient_Sensor_On = True

if Ambient_Sensor_On:
	import adafruit_veml7700
	veml7700 = adafruit_veml7700.VEML7700(i2c)


### The code itself!

#Here I initialize the CO2 sensor and take the first reading
while True:
	
	if CO2_sensor.data_ready:
		print("C02: %d ppm" % CO2_sensor.CO2)
		print("CO2_Temperature: %0.1f *C" % CO2_sensor.temperature)
		print("CO2_Humidity: %0.1f %%" % CO2_sensor.relative_humidity)
		CO2_temp_C = round(CO2_sensor.temperature, 1)
		CO2_humidity = round(CO2_sensor.relative_humidity, 1)
		CO2_CO2 = CO2_sensor.CO2
		break
		
#Once the CO2 sensor is ready, we get things going.

counter = 0
start_time = "{}-{}-{}_{}:{}".format(time.localtime().tm_mon, time.localtime().tm_mday, time.localtime().tm_year, time.localtime().tm_hour, time.localtime().tm_min)
print("Starting to measure at {}".format(start_time))
with open("data_logger_{}.csv".format(start_time), "w") as data_file:
	datawriter = csv.writer(data_file, delimiter = ",")
	datawriter.writerow(data_header)

while True:
	
	data = [time.localtime().tm_mon, time.localtime().tm_mday, time.localtime().tm_year, time.localtime().tm_hour, time.localtime().tm_min, time.localtime().tm_sec]
	
	if Color_Sensor_On:
		red = light_sensor.color_rgb_bytes[0]
		green = light_sensor.color_rgb_bytes[1]
		blue = light_sensor.color_rgb_bytes[2]
		print("R:" + str(red) + " G:" + str(green) + " B:" + str(blue))
		data.append([red, green, blue])

	if BME280_Sensor_On:
		BME_humidity = round(bme280.humidity, 1)
		BME_pressure = round(bme280.pressure, 1)
		BME_temp = round(bme280.temperature, 1)
		print("BME_Temp: {}, BME_Pressure: {}, BME_Humidity: {}".format(BME_temp, BME_pressure, BME_humidity))
		data.append([BME_temp, BME_humidity, BME_pressure])
		
	if CO2_Sensor_On:
		if CO2_sensor.data_ready:
			CO2_temp_C = round(CO2_sensor.temperature, 1)
			CO2_humidity = round(CO2_sensor.relative_humidity, 1)
			CO2_CO2 = CO2_sensor.CO2
		CO2_temp_F = round(CO2_temp_C * (9/5) + 32, 1) 
		print("CO2_Temp: {} *F".format(CO2_temp_F))
		print("CO2: {} ppm".format(CO2_CO2))
		print("CO2_Humid: {} %".format(CO2_humidity))
		data.extend([CO2_temp_F, CO2_humidity, CO2_CO2])
		
	if Light_Sensor_On:
		lux = round(Light_sensor.lux, 1)
		visible = Light_sensor.visible
		IR = Light_sensor.infrared
		print("Brightness: {}, Visible Light: {}, Infrared Light: {}".format(lux, visible, IR))
		data.extend([lux, visible, IR])

	if Accel_Sensor_On:
		print("Acceleration (m/s^2): X=%0.3f Y=%0.3f Z=%0.3f"%accel.acceleration)
		print("Magnetometer (micro-Teslas)): X=%0.3f Y=%0.3f Z=%0.3f"%mag.magnetic)

	if UV_Sensor_On:
		print("UV:", ltr.uvs, "Ambient Light:", ltr.light)
		print("UVI:", ltr.uvi, "Lux:", ltr.lux)

	if Ambient_Sensor_On:
		print("Ambient light:", veml7700.light)
		print("Lux:", veml7700.lux)

	if BMP388_Sensor_On:
		print("Pressure: {:6.4f} hPa  Temperature: {:5.2f} *C".format(bmp.pressure, bmp.temperature,))
		print('Altitude: {} meters'.format(bmp.altitude))
    

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
			
	sleep(Sensor_Interval)
