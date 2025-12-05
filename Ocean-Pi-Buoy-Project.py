import datetime
import time
import os
import serial
import board
import csv
import paho.mqtt.client as mqtt
import json
import busio
import base64
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from PIL import Image
import io

sleep = time.sleep

#----------------------------------------------------------------------
# --- Notes --- #
#----------------------------------------------------------------------
'''
To-Do List:
# I currently have two competing data formatting schemes (not sure how that happened), which needs to be cleaned up
# Add the UART conductivity sensor

All packages for the sensors are installed in a Virtual Environment. You can create a Virtual Environment by running "python -m venv venv-ocean-pi"
in the home directory (/planetschool, on our pi)

To activate, run 'source venv-ocean-pi/bin/activate'

Depending on the sensors you choose to install on your buoy, the following sensor packages are required to be installed inside the Virtual Environment (venv-ocean-pi) before running this program:
pip3 install adafruit-circuitpython-sgp40
pip3 install adafruit-circuitpython-bmp3xx
pip3 install adafruit-circuitpython-scd4x
pip3 install adafruit-circuitpython-tsl2591
pip3 install adafruit-circuitpython-ltr390
pip3 install adafruit-circuitpython-lis2mdl
pip3 install adafruit-circuitpython-lsm303-accel
pip3 install adafruit-circuitpython-veml7700
pip3 install adafruit-circuitpython-bno08x
pip3 install adafruit-circuitpython-bme680
pip3 install adafruit-circuitpython-ina23x

pip3 install adafruit-circuitpython-ads1x15 

To use the LCD screen, you need to install the LCD driver in the same folder as this code file. In the terminal, run:
wget https://gist.githubusercontent.com/DenisFromHR/cc863375a6e19dce359d/raw/36b82e787450d127f5019a40e0a55b08bd43435a/RPi_I2C_driver.py
'''
#----------------------------------------------------------------------
# --- Camera Setup --- #
#----------------------------------------------------------------------
Camera_On = True
picam2 = Picamera2()
config = picam2.create_still_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

def create_snapshot():
	# Capture raw RGB frame
	frame = picam2.capture_array()

	# Encode to JPEG with given quality
	buf = io.BytesIO()
	Image.fromarray(frame).save(buf, format="JPEG", quality=50)   # <-- control size here
	jpeg_bytes = buf.getvalue()
	return jpeg_bytes


#----------------------------------------------------------------------
# --- Sensor Selection --- #
#----------------------------------------------------------------------
## Buoy Sensors
Analog_Digital_Converter_On = True		#ads1115 analog to digital converter. Requires "pip3 install adafruit-circuitpython-ads1x15"
Motion_Sensor_On = True					#BNO085 9-DOF sensor. Requires "pip3 install adafruit-circuitpython-bno08x-rvc"
Light_Sensor_On = True					#tsl2590 sensor. Requires "pip3 install adafruit-circuitpython-tsl2591"
BME680_Sensor_On = True					#Temp, pressure, humidity, gas. Requires "pip3 install adafruit-circuitpython-bme680"
Power_Sensor_On = True					#INA238 volt, current, power sensor. Requires "pip3 install adafruit-circuitpython-ina23x"

## Other Sensors/Peripherals
LCD_On = False							#Requires you to download a library from Github. See above.
Gas_Sensor_On = False					#spg40 sensor. Requires "pip3 install adafruit-circuitpython-sgp40"
Color_Sensor_On = False					#tcs34725 sensor
Temp_Press_Humidity_Sensor_On = False	#bme280 sensor. Requires "pip3 install adafruit-circuitpython-bmp3xx"
Precision_Press_Temp_Sensor_On = False	#bmp388 sensor NOTE: uses i2c address 0x77, so cannot be attached to the same pi as BME280
CO2_Sensor_On = False					#scd41 sensor. Requires "pip3 install adafruit-circuitpython-scd4x"
Accel_Magnet_Sensor_On = False			#lsm303 sensor. Requires "pip3 install adafruit-circuitpython-lsm303-accel"
UV_Sensor_On = False					#ltr390 sensor. Requires "pip3 install adafruit-circuitpython-ltr390"
Ambient_Sensor_On = False				#veml7700 sensor. Requires "pip3 install adafruit-circuitpython-veml7700"


#----------------------------------------------------------------------
# --- Network Settings --- #
#----------------------------------------------------------------------
ACCESS_TOKEN = os.environ.get("THINGSBOARD_TOKEN")
THINGSBOARD_HOST = "thingsboard.cloud"
PORT = 1883
PUBLISH_INTERVAL = 10  # seconds
MQTT_TOPIC = "v1/devices/me/telemetry"

### Start the Network
client = mqtt.Client()
client.username_pw_set(ACCESS_TOKEN)
client.connect(THINGSBOARD_HOST, PORT, 60)
client.loop_start()



#----------------------------------------------------------------------
# --- I2C Settings --- #
#----------------------------------------------------------------------
i2c_port = 1

### I2C Addresses
### Buoy Sensors
adc_dfrobot_address = 0x4b		#I put all my DFRobot sensors on this ADC
adc_atlas_address = 0x48		#I put all my Atlas sensors on this ADC
tsl2590_light_address = 0x29 
bno085_address = 0x4a
bme688_address = 0x77
ina238_address = 0x40

### Other Sensor/Peripherals
sgp40_mox_gas_address = 0x59
tcs34725_RGB_address = 0x29
bme280_temp_pres_hum_address = 0x77 
scd41_co2_address = 0x62 
lcd_address = 0x27
ltr390_lightUV_address = 0x53
veml7700_light_address = 0x10
lsm303agr_accel_magnet_address = 0x19 + 0x1e #unsure of why two addresses
bmp388_precision_alt_temp_pres_address = 0x77 #uses the same address as BME280


#----------------------------------------------------------------------
# --- Buoy Sensor Configuration --- #
#----------------------------------------------------------------------
DEVICE_ID = "Weather Buoy Alpha"
i2c = board.I2C()
Sensor_Interval = 5		# Number of seconds between polling the sensor array
data_header = ["Month", "Day", "Year", "Hour", "Minute", "Second"]

### Light Sensor (TSL2591):	https://docs.circuitpython.org/projects/ads1x15
if Light_Sensor_On:
	import adafruit_tsl2591 as Light
	Light_sensor = Light.TSL2591(i2c, int(tsl2590_light_address))
	lux = Light_sensor.lux
	visible = Light_sensor.visible		
	IR = Light_sensor.infrared
	data_header.extend(["Brightness (lux)", "Visible Light", "Infrared Light"])
	print("Testing light sensor...")
	print("Brightness: {}, Visible Light: {}, Infrared Light: {}".format(lux, visible, IR))

### Analog to Digital Converter (ADS1115)
if Analog_Digital_Converter_On:
	from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15
	ads_dfrobot = ADS1115(i2c, address=int(adc_dfrobot_address))
	tds_sensor = AnalogIn(ads_dfrobot, ads1x15.Pin.A0)
	turbidity_sensor = AnalogIn(ads_dfrobot, ads1x15.Pin.A1)
	#pH_sensor = AnalogIn(ads_dfrobot, ads1x15.Pin.A2)	#Using an Atlas pH sensor
	water_temp_sensor = AnalogIn(ads_dfrobot, ads1x15.Pin.A3)
	print("Testing analog sensors...")
	print("Water Temp Value: {}, Water Temp Sensor Volts: {}, "
	"TDS Value: {}, TDS Sensor Volts: {}, Turbidity Value: {}, "
	"Turbidity Sensor Volts: {}".format(water_temp_sensor.value, 
	water_temp_sensor.voltage, tds_sensor.value, tds_sensor.voltage,
	turbidity_sensor.value, turbidity_sensor.voltage))
	data_header.extend(["Water Temp Value, Water Temp Sensor Volts, TDS Value, TDS Sensor Volts, Turbidity Value, Turbidity Sensor Volts"])
	
	ads_atlas = ADS1115(i2c, address=int(adc_atlas_address))
	pH_sensor = AnalogIn(ads_atlas, ads1x15.Pin.A1)
	ORP_sensor = AnalogIn(ads_atlas, ads1x15.Pin.A0)
	print("pH Value: {}, pH Volts: {}, "
	"ORP Value: {}, ORP Volts: {}".format(pH_sensor.value, 
	pH_sensor.voltage, ORP_sensor.value, ORP_sensor.voltage))
	
### Motion Sensor (BNO085):	https://docs.circuitpython.org/projects/bno08x
if Motion_Sensor_On:
	from adafruit_bno08x.i2c import BNO08X_I2C
	from adafruit_bno08x import (
    BNO_REPORT_ACCELEROMETER,
    BNO_REPORT_GYROSCOPE,
    BNO_REPORT_MAGNETOMETER,
    BNO_REPORT_ROTATION_VECTOR,
	)	
	bno = BNO08X_I2C(i2c)
	bno.enable_feature(BNO_REPORT_ACCELEROMETER)
	bno.enable_feature(BNO_REPORT_GYROSCOPE)
	bno.enable_feature(BNO_REPORT_MAGNETOMETER)
	bno.enable_feature(BNO_REPORT_ROTATION_VECTOR)
	
	print("Testing motion sensor...")
	x_accel, y_accel, z_accel = bno.acceleration
	#print("Yaw: {}, Pitch: {}, Roll: {}, X Acceleration: {}, Y Accelleration: {}, Z Accelleration: {}".format(yaw, pitch, roll, x_accel, y_accel, z_accel))
	print("X Acceleration: {}, Y Accelleration: {}, Z Accelleration: {}".format(x_accel, y_accel, z_accel))
	print("Gyro:")
	gyro_x, gyro_y, gyro_z = bno.gyro
	print("X: %0.6f  Y: %0.6f Z: %0.6f rads/s" % (gyro_x, gyro_y, gyro_z))
	print("Magnetometer:")
	mag_x, mag_y, mag_z = bno.magnetic
	print("X: %0.6f  Y: %0.6f Z: %0.6f uT" % (mag_x, mag_y, mag_z))
	print("Rotation Vector Quaternion:")
	quat_i, quat_j, quat_k, quat_real = bno.quaternion
	print("I: %0.6f  J: %0.6f K: %0.6f  Real: %0.6f" % (quat_i, quat_j, quat_k, quat_real))
	
### BME680 Temperature, Pressure, Humidity, Gas Sensor:	https://docs.circuitpython.org/projects/bme680
if BME680_Sensor_On:
	from adafruit_bme680 import Adafruit_BME680_I2C
	atmosphere = Adafruit_BME680_I2C(i2c)
	print("Testing atmospheric sensor...")
	print("Temp: {} °C, Pressure: {} hPa,  Humidity: {} %, Gas: {} ohm, Altitude: {} m".format(atmosphere.temperature, atmosphere.pressure, atmosphere.relative_humidity, atmosphere.gas, atmosphere.altitude))
	
### Power Sensor (INA238):	https://docs.circuitpython.org/projects/ina23x
if Power_Sensor_On:
	from adafruit_ina23x import INA23X
	electrical = INA23X(i2c)
	print("Testing power sensor...")
	print(f"Current: {electrical.current * 1000:.2f} mA")
	print(f"Bus Voltage: {electrical.bus_voltage:.2f} V")
	print(f"Shunt Voltage: {electrical.shunt_voltage * 1000:.2f} mV")
	print(f"Power: {electrical.power * 1000:.2f} mW")
	print(f"Temperature: {electrical.die_temperature:.2f} °C")
	


#----------------------------------------------------------------------
# --- Other Sensor/Peripherals Configuration --- #
#----------------------------------------------------------------------
### LCD Display                                                                                                   
if LCD_On:
	import RPi_I2C_driver
	
	mylcd = RPi_I2C_driver.lcd()
	mylcd.lcd_display_string("Starting up the", 1)
	mylcd.lcd_display_string("Weather Station", 2)

### Mox Gas Sensor (SGP40)
if Gas_Sensor_On:
    import adafruit_sgp40
    try:
        sgp = adafruit_sgp40.SGP40(i2c, int(sgp40_mox_gas_address))
        print("Raw gas: ", sgp.raw)
        data_header.extend(["Raw Gas"])
    except Exception as e:
        print("SGP40 read failed:", e)
        sgp40_mox_raw = None

### Color Sensor (TCS34725)
if Color_Sensor_On:
	import adafruit_tcs34725
	light_sensor = adafruit_tcs34725.TCS34725(i2c, int(tcs34725_RGB_address))
	#print(light_sensor.color_rgb_bytes)
	data_header.extend(["Red Light", "Green Light", "Blue Light"])
	
### Temp, Pressure, Humidity (BME280)
if Temp_Press_Humidity_Sensor_On:
	from adafruit_bme280 import basic as adafruit_bme280
	import smbus2
	bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c)
	BME_humidity = bme280.humidity
	BME_pressure = bme280.pressure
	BME_temp = bme280.temperature
	data_header.extend(["BME Temperature (*F)", "BME Humidity (%)", "BME Pressure (hPa)"])
	#print("Temp: {}, Pressure: {}, Humidity: {}".format(BME_temp, BME_pressure, BME_humidity))

### Temp, Pressure, Altitude (BMP388)
if Precision_Press_Temp_Sensor_On:
	import adafruit_bmp3xx
	bmp = adafruit_bmp3xx.BMP3XX_I2C(i2c)
	bmp.sea_level_pressure = 1013.25 #Need to establish sea level pressure in order to extrapolate altitude. Fun project opportunity here.
	bmp.pressure_oversampling = 8
	bmp.temperature_oversampling = 2
	data_header.extend(["BMP Temperature (*F)", "BMP Altitude (m)", "BMP Pressure (hPa)"])

### CO2 Sensor (SCD41)
if CO2_Sensor_On:
	import adafruit_scd4x as CO2
	CO2_sensor = CO2.SCD4X(i2c, int(scd41_co2_address))
	CO2_sensor.start_periodic_measurement()
	print("Waiting for first measurement...")
	data_header.extend(["CO2 Temperature (*F)", "CO2 Humidity (%)", "CO2 PPM"])

### Accelerometer and Magnetometer (LSM303)
if Accel_Magnet_Sensor_On:
	import adafruit_lsm303_accel
	import adafruit_lis2mdl
	accel = adafruit_lsm303_accel.LSM303_Accel(i2c)
	mag = adafruit_lis2mdl.LIS2MDL(i2c)
	data_header.extend(["Acceleration (m/s^2), Magnetometer (micro-Teslas)"])

### UV Sensor (LTR390)
if UV_Sensor_On:
	import adafruit_ltr390
	ltr = adafruit_ltr390.LTR390(i2c)
	data_header.extend(["UV Raw, Ambient Light Raw, UV Index, Ambient Light Index"])

### Ambient Light Sensor (VEML7700)
if Ambient_Sensor_On:
	import adafruit_veml7700
	veml7700 = adafruit_veml7700.VEML7700(i2c)



#----------------------------------------------------------------------
# --- Buoy Code --- #
#----------------------------------------------------------------------
Buoy_On = True
print(data_header)
#Here I initialize the CO2 sensor and take the first reading

while True:
	if CO2_Sensor_On:
		if CO2_sensor.data_ready:
			print("C02: %d ppm" % CO2_sensor.CO2)
			print("CO2_Temperature: %0.1f *C" % CO2_sensor.temperature)
			print("CO2_Humidity: %0.1f %%" % CO2_sensor.relative_humidity)
			CO2_temp_C = round(CO2_sensor.temperature, 1)
			CO2_humidity = round(CO2_sensor.relative_humidity, 1)
			CO2_CO2 = CO2_sensor.CO2
			break
			
	else:
		break

#Once the CO2 sensor is ready, we get things going.

while Buoy_On:
	print("New Measurement: ")

	run_weather_station = True
	
	payload = {
		"device_id": DEVICE_ID,
		"timestamp": datetime.datetime.utcnow().isoformat() + "Z",

		"tsl2591_lux": None,
		"tsl2591_visible": None,
		"tsl2591_IR": None,
		
		"water_temp_C": None,
		"water_temp_F": None,
		"tds": None,
		"turbidity": None,
		
		"x_accel": None, 
		"y_accel": None, 
		"z_accel": None,
		"gyro_x": None,
		"gyro_y": None,
		"gyro_z": None,
		"mag_x": None,
		"mag_y": None,
		"mag_z": None,
		"quat_i": None,
		"quat_j": None,
		"quat_k": None,
		"quat_real": None,
		
		"snapshot": None,
		
    	}
	if Camera_On:
		jpeg_bytes = create_snapshot()
		pic = base64.b64encode(jpeg_bytes).decode("utf-8")
		print("length of the pic is:", len(pic))
		payload["snapshot"] = pic
		
		
	if Color_Sensor_On:
		try:
			red = light_sensor.color_rgb_bytes[0]
			green = light_sensor.color_rgb_bytes[1]
			blue = light_sensor.color_rgb_bytes[2]
			print("R:" + str(red) + " G:" + str(green) + " B:" + str(blue))
		except Exception:
			pass

	if Temp_Press_Humidity_Sensor_On:
		try:
			BME_humidity = round(bme280.humidity, 1)
			BME_pressure = round(bme280.pressure, 1)
			BME_temp = round(bme280.temperature, 1)
			print("BME_Temp: {}, BME_Pressure: {}, BME_Humidity: {}".format(BME_temp, BME_pressure, BME_humidity))
		except Exception:
			pass
	
	if CO2_Sensor_On:
		try:
			if CO2_sensor.data_ready:
				CO2_temp_C = round(CO2_sensor.temperature, 1)
				CO2_humidity = round(CO2_sensor.relative_humidity, 1)
				CO2_CO2 = CO2_sensor.CO2
				CO2_temp_F = round(CO2_temp_C * (9/5) + 32, 1) 
				print("CO2_Temp: {} *F".format(CO2_temp_F))
				print("CO2: {} ppm".format(CO2_CO2))
				print("CO2_Humid: {} %".format(CO2_humidity))
				payload["scd41_co2_ppm"] = CO2_CO2
				payload["scd41_humidity_%"] = CO2_humidity
				payload["scd41_temperature_F"] = CO2_temp_F		
		except Exception:
			pass
		
	if Light_Sensor_On:
		try:
			lux = round(Light_sensor.lux, 1)
			visible = Light_sensor.visible
			IR = Light_sensor.infrared
			print("Brightness: {}, Visible Light: {}, Infrared Light: {}".format(lux, visible, IR))
			#data.extend([lux, visible, IR])
			payload["tsl2591_lux"] = lux
			payload["tsl2591_visible"] = visible
			payload["tsl2591_IR"] = IR
		except Exception:
			pass

	if Accel_Magnet_Sensor_On:
		try:
			print("Acceleration (m/s^2): X=%0.3f Y=%0.3f Z=%0.3f"%accel.acceleration)
			print("Magnetometer (micro-Teslas)): X=%0.3f Y=%0.3f Z=%0.3f"%mag.magnetic)
			payload["lsm303_acceleration_m/s^2"] = accel.acceleration
			payload["lsm303_magnetometer_microTeslas"] = mag.magnetic
		except Exception:
			pass

	if UV_Sensor_On:
		try:
			UV = ltr.uvs
			ambient = ltr.light
			UVi = ltr.uvi
			lux = ltr.lux
			print("UV:", UV, "Ambient Light:", ambient)
			print("UVI:", UVi, "Lux:", lux)
			payload["ltr390_UV_raw"] = UV
			payload["ltr390_UV_index"] = UVi
			payload["ltr390_ambient_raw"] = ambient
			payload["ltr390_ambient_index"] = lux
		except Exception:
			pass
			
	if Gas_Sensor_On:
		try:
			mox = sgp.raw
			payload["sgp40_mox_raw"] = mox
		except Exception:
			pass

	if Ambient_Sensor_On:
		try:
			ambient = veml7700.light
			lux = veml7700.lux
			print("Ambient light:", ambient)
			print("Lux:", lux)
			payload["veml7700_ambient"] = ambient
			payload["veml7700_lux"] = lux
		except Exception:
			pass

	if Precision_Press_Temp_Sensor_On:
		try:
			pressure = bmp.pressure
			temp = bmp.temperature
			print("Pressure: {:6.4f} hPa  Temperature: {:5.2f} *C".format(pressure, temp,))
			print('Altitude: {} meters'.format(bmp.altitude))
			payload["bmp388_pressure_hpa"] = pressure
			payload["bmp388_temperature_C"] = temp
		except Exception:
			pass
			
	if Analog_Digital_Converter_On:
		try:
			tds_value = tds_sensor.value	
			
			temperature_value = water_temp_sensor.value
			water_temp_volts = water_temp_sensor.voltage
			float(temperature_value)
			temperature_value = temperature_value/1000
			water_temp_F = (temperature_value * 9/5) + 32
			payload["water_temp_C"] = temperature_value
			payload["water_temp_F"] = water_temp_F
			
			tds = tds_sensor.value
			tds_volts = tds_sensor.voltage
			payload["tds"] = tds
			
			turbidity = turbidity_sensor.value
			turbidity_volts = turbidity_sensor.voltage
			payload["turbidity"] = turbidity

			print("Water Temp: {} °F, Water Temp Volts: {} V, TDS: {}, TDS Volts: {} V, Turbidity: {}, Turbidity Volts: {} V".format(water_temp_F, water_temp_volts, tds, tds_volts,turbidity, turbidity_volts))

			pH = pH_sensor.value
			pH_volts = pH_sensor.voltage
			payload["pH"] = pH
			
			ORP = ORP_sensor.value
			ORP_volts = ORP_sensor.voltage
			payload["ORP"] = ORP
			
			print("pH: {}, pH Volts: {} V, ORP: {}, ORP Volts: {} V".format(pH, pH_volts, ORP, ORP_volts))

		except Exception:
			print("Water sensors failed")
			pass
			
	if Motion_Sensor_On:
		try:
			x_accel, y_accel, z_accel = bno.acceleration
			print("X Acceleration: {}, Y Accelleration: {}, Z Accelleration: {}".format(x_accel, y_accel, z_accel))
			print("Gyro:")
			gyro_x, gyro_y, gyro_z = bno.gyro
			print("X: %0.6f  Y: %0.6f Z: %0.6f rads/s" % (gyro_x, gyro_y, gyro_z))
			print("Magnetometer:")
			mag_x, mag_y, mag_z = bno.magnetic
			print("X: %0.6f  Y: %0.6f Z: %0.6f uT" % (mag_x, mag_y, mag_z))
			print("Rotation Vector Quaternion:")
			quat_i, quat_j, quat_k, quat_real = bno.quaternion
			print("I: %0.6f  J: %0.6f K: %0.6f  Real: %0.6f" % (quat_i, quat_j, quat_k, quat_real))
			print(x_accel, y_accel, z_accel)
			payload["x_accel"] = x_accel
			payload["y_accel"] = y_accel
			payload["z_accel"] = z_accel
			payload["gyro_x"] = gyro_x
			payload["gyro_y"] = gyro_y
			payload["gyro_z"] = gyro_z
			payload["mag_x"] = mag_x
			payload["mag_y"] = mag_y
			payload["mag_z"] = mag_z
			payload["quat_i"] = quat_i
			payload["quat_j"] = quat_j
			payload["quat_k"] = quat_k
			payload["quat_real"] = quat_real
		except Exception:
			print("Motion sensor failed")
			pass
	
#the LCD/display code will need to be rethought since it presents the data more slowly (scrolling through several screens) than the data is gathered.
	if LCD_On:
		mylcd.lcd_clear()
		if Light_Sensor_On:
			mylcd.lcd_clear()
			mylcd.lcd_display_string("Bright: {} Lux".format(lux), 1)
			mylcd.lcd_display_string("IR: {} , Vis: {}".format(IR, visible), 2)
			sleep(2)
		if Temp_Press_Humidity_Sensor_On:
			mylcd.lcd_clear()
			mylcd.lcd_display_string("Press: {} hPa".format(BME_pressure), 1)
			mylcd.lcd_display_string("Humid: {} %".format(BME_humidity), 2)
			sleep(2)
		if CO2_Sensor_On:
			mylcd.lcd_clear()
			mylcd.lcd_display_string("Temp: {} *F".format(CO2_temp_F), 1)
			mylcd.lcd_display_string("CO2: {} ppm".format(CO2_CO2), 2) 
			sleep(2)
			mylcd.lcd_clear()
			mylcd.lcd_display_string("Humid: {} %".format(CO2_humidity), 1)
			sleep(2)
		if Color_Sensor_On:
			mylcd.lcd_clear()
			mylcd.lcd_display_string("R:" + str(red) + " G:" + str(green) + " B:" + str(blue), 1)
			sleep(2)
	
	print("  ") #creates a line break in the terminal, which is visually easier to see each new data output
	
	print(payload)
	# --- Publish MQTT ---
	try:
		client.publish(MQTT_TOPIC, json.dumps(payload))
		#print(f"[PUBLISH] {payload}")
	except Exception as e:
		print(f"[ERROR] MQTT publish failed: {e}")

