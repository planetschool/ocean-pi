import datetime
import time
import os
import serial
import board
import csv
import paho.mqtt.client as mqtt
import json
import busio

sleep = time.sleep

#To-Do List:
# I currently have two competing data formatting schemes (not sure how that happened), which needs to be cleaned up
# Motion sensor is not working


'''
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
pip3 install adafruit-circuitpython-bno08x-rvc

pip3 install adafruit-circuitpython-ads1x15 

To use the LCD screen, you need to install the LCD driver in the same folder as this code file. In the terminal, run:
wget https://gist.githubusercontent.com/DenisFromHR/cc863375a6e19dce359d/raw/36b82e787450d127f5019a40e0a55b08bd43435a/RPi_I2C_driver.py
'''

# --- Sensor Selection --- #
LCD_On = False
Gas_Sensor_On = False					#spg40 sensor
Color_Sensor_On = False					#tcs34725 sensor
Temp_Press_Humidity_Sensor_On = False	#bme280 sensor  
Precision_Press_Temp_Sensor_On = False	#bmp388 sensor NOTE: uses i2c address 0x77, so cannot be attached to the same pi as BME280
CO2_Sensor_On = False					#scd41 sensor
Light_Sensor_On = True					#tsl2590 sensor
Accel_Magnet_Sensor_On = False			#lsm303 sensor
UV_Sensor_On = False					#ltr390 sensor
Ambient_Sensor_On = False				#veml7700 sensor
Analog_Digital_Converter_On = False		#ads1115 analog to digital converter
Motion_Sensor_On = True					#BNO085 9-DOF sensor


# --- Network Settings --- #
ACCESS_TOKEN = os.environ.get("THINGSBOARD_TOKEN")
THINGSBOARD_HOST = "thingsboard.cloud"
PORT = 1883
PUBLISH_INTERVAL = 10  # seconds
MQTT_TOPIC = "v1/devices/me/telemetry"

# --- I2C Settings --- #
i2c_port = 1
sgp40_mox_gas_address = 0x59 #present but does not show in i2cdetect for some reason
tcs34725_RGB_address = 0x29 #present
bme280_temp_pres_hum_address = 0x77 #present? or bmp388?
scd41_co2_address = 0x62 #present
lcd_address = 0x27 #present
tsl2590_light_address = 0x29 #present
ltr390_lightUV_address = 0x53 #present
veml7700_light_address = 0x10 #present
lsm303agr_accel_magnet_address = 0x19 + 0x1e #present and unsure of why two addresses
bmp388_precision_alt_temp_pres_address = 0x77 #present? or bme280?
analog_digital_converter_address = 0x48


# --- Sensor Configuration --- #
DEVICE_ID = "Weather Buoy Alpha"
i2c = board.I2C()
Sensor_Interval = 5		# Number of seconds between polling the sensor array
data_header = ["Month", "Day", "Year", "Hour", "Minute", "Second"]

#### LCD Display                                                                                                   
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

### Light Sensor (TSL2591)
if Light_Sensor_On:
	import adafruit_tsl2591 as Light
	Light_sensor = Light.TSL2591(i2c, int(tsl2590_light_address))
	lux = Light_sensor.lux
	visible = Light_sensor.visible		
	IR = Light_sensor.infrared
	data_header.extend(["Brightness (lux)", "Visible Light", "Infrared Light"])
	#print("Brightness: {}, Visible Light: {}, Infrared Light: {}".format(lux, visible, IR))

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
	
### Analog to Digital Converter (ADS1115)
if Analog_Digital_Converter_On:
	from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15
	ads = ADS1115(i2c)
	tds_sensor = AnalogIn(ads, ads1x15.Pin.A0)
	turbidity_sensor = AnalogIn(ads, ads1x15.Pin.A1)
	pH_sensor = AnalogIn(ads, ads1x15.Pin.A2)
	water_temperature_sensor = AnalogIn(ads, ads1x15.Pin.A3)
	data_header.extend(["pH Value, pH Sensor Volts, Water Temp Value, Water Temp Sensor Volts, TDS Value, TDS Sensor Volts, Turbidity Value, Turbidity Sensor Volts"])
	
### Motion Sensor (BNO085):
if Motion_Sensor_On:
	from adafruit_bno08x_rvc import BNO08x_RVC
	motion = BNO08x_RVC(i2c)


# --- Initialize MQTT Publishing --- #
client = mqtt.Client()
client.username_pw_set(ACCESS_TOKEN)
client.connect(THINGSBOARD_HOST, PORT, 60)
client.loop_start()


# --- Buoy Code --- #
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
		
		"bmp388_pressure_hpa": None,
		"bmp388_temperature_C": None,

		"sgp40_mox_raw": None,
		
		"scd41_co2_ppm": None,
		"scd41_humidity_%": None,
		"scd41_temperature_F": None,

		"tsl2591_lux": None,
		"tsl2591_visible": None,
		"tsl2591_IR": None,

		"ltr390_UV_raw": None,
		"ltr390_UV_index": None,
		"ltr390_ambient_raw": None,
		"ltr390_ambient_index": None,

		"veml7700_ambient": None,
		"veml7700_lux": None,

		"lsm303_acceleration_m/s^2": None,
		"lsm303_magnetometer_microTeslas": None,
		
    	}
		
	if Color_Sensor_On:
		try:
			red = light_sensor.color_rgb_bytes[0]
			green = light_sensor.color_rgb_bytes[1]
			blue = light_sensor.color_rgb_bytes[2]
			print("R:" + str(red) + " G:" + str(green) + " B:" + str(blue))
			#data.append([red, green, blue])
		except Exception:
			pass

	if Temp_Press_Humidity_Sensor_On:
		try:
			BME_humidity = round(bme280.humidity, 1)
			BME_pressure = round(bme280.pressure, 1)
			BME_temp = round(bme280.temperature, 1)
			print("BME_Temp: {}, BME_Pressure: {}, BME_Humidity: {}".format(BME_temp, BME_pressure, BME_humidity))
			#data.append([BME_temp, BME_humidity, BME_pressure])
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
			#data.extend([CO2_temp_F, CO2_humidity, CO2_CO2])
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
			
			temperature_value = water_temperature_sensor.value
			float(temperature_value)
			temperature_value = temperature_value/1000
			temperature_value = (temperature_value * 9/5) + 32
			
			pH_value = pH_sensor.value
			
			turbidity_value = turbidity_sensor.value

			print("Water Temperature: {} *F, {} volts".format(temperature_value, water_temperature_sensor.voltage))
			print("pH: {}, {} volts  Total Dissolved Solids: {}, {} volts".format(pH_value, pH_sensor.voltage, tds_value, tds_sensor.voltage))
			print("Turbidity: {}, {} volts".format(turbidity_value, turbidity_sensor.voltage))
		except Exception:
			print("Water sensors failed")
			pass
			
	if Motion_Sensor_On:
		try:
			yaw, pitch, roll, x_accel, y_accel, z_accel = motion.heading
			print("Yaw: {}, Pitch: {}, Roll: {}, X Acceleration: {}, Y Accelleration: {}, Z Accelleration: {}".format(yaw, pitch, roll, x_accel, y_accel, z_accel))
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
	

	# --- Publish MQTT ---
	try:
		client.publish(MQTT_TOPIC, json.dumps(payload))
		#print(f"[PUBLISH] {payload}")
	except Exception as e:
		print(f"[ERROR] MQTT publish failed: {e}")

