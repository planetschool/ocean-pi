# ocean-pi
Code, guides, and samples to help you run your code at sea aboard the Planet School's sailing research vessel, Wonder.

(4/28/2025) Alright, going to take notes here as I revisit this code for the first time in several months. I am working on building the full science station on Wonder and my current thinking is that I will have a centralized Raspberry Pi 5 running OceanPlotter that will act as the "Ocean Hub" and gather data from several other Raspberry Pi computers (mostly Pi Zero 2 W's) scattered around the ship connected to sensor arrays. These "node" Raspberry Pi computers include:
1) RPi 4B with attached SenseHat and Camera mounted on the nav station on the quarterdeck in a watertight case, facing forward.
2) RPi Zero 2W attached to the atmosphere sensor array mounted midships at the science station.
3) RPi Zero 2W attached to Wonder's NMEA 2000 backbone pulling data from all of the ship's systems (GPS, AIS, Weather, Radio, Course, Speed, etc.). This computer is currently mounted at the nav station, but I would like to move it to the electrical panel below deck.
4) RPi Zero 2W attached to the ocean sensor array mounted midships at the science station.
5) RPi Zero 2W attached to a camera, mounted at the tip of the bowsprit facing aft (this one will be challenging, but the footage will look awesome).

First issue is installing the dependencies (as usual). After the first step of creating the virtual environment using "python -m venv venv-ocean-pi" inside my root folder "planetschool," I ran "source venv-ocean-pi/bin/activate". Here are the dependencies I have installed:
1) pip3 install gpiozero
2) pip3 install pyserial
3) pip3 install board

When setting up the Pi, ensure that SSH, I2C, and Serial are all enabled using "sudo raspi-config"

I am now getting a serial error, so I am making sure Bluetooth does not use the serial port I am trying to use. I recall this from before. I have tried adding this line to "/boot/config.txt":

"# Disable Bluetooth if you want the full hardware UART (recommended for sensors)
dtoverlay=disable-bt"

I also disabled Bluetooth with "sudo systemctl disable hciuart"

Ok, that fixed the UART serial data error.

I need to download a driver for the LCD screen, which I got here: https://gist.github.com/DenisFromHR/cc863375a6e19dce359d
I used "wget https://gist.githubusercontent.com/DenisFromHR/cc863375a6e19dce359d/raw/36b82e787450d127f5019a40e0a55b08bd43435a/RPi_I2C_driver.py"



