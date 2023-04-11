import ctypes
import time
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def bc(i):
    return ctypes.c_byte(i)


def twobc(i):
    i_h = int(i / 256)
    i_l = i - int(i / 128) * 256
    a = (ctypes.c_byte * 2)()
    a[0] = i_h
    a[1] = i_l
    return a


def cbyte2int(inputnum):
    return (inputnum & 0xff)


class UsbI2c:
    def __init__(self, address_width):
        """
        初始化函数，加载库并设定寄存器地址宽度等参数
        :param address_width: 寄存器地址宽度，8或16
        """
        # 加载库文件
        self.dll = ctypes.cdll.LoadLibrary("./usb2uis.dll")
        # 设定参数
        self.address_width = address_width
        self.p_buf = ctypes.byref(bc(0xff))
        self.DevAddr = ctypes.byref(bc(0xff))
        self.pbyRate = ctypes.byref(bc(0xff))
        self.poutdata = ctypes.byref(bc(0xff))
        self.dll.USBIO_OpenDevice.restype = ctypes.c_bool
        self.dll.USBIO_I2cGetConfig.restype = ctypes.c_bool
        self.dll.USBIO_I2cSetConfig.restype = ctypes.c_bool
        self.dll.USBIO_I2cAutoGetAddress.restype = ctypes.c_bool
        # 初始化
        self.i2cinit()

    def open_i2c_device(self):
        """
        打开USB-I2C设备
        """
        # 关闭设备
        logging.info(f'CloseI2C: {self.dll.USBIO_CloseDevice(bc(0))}')
        time.sleep(0.01)
        # 打开设备
        self.ID = bc(self.dll.USBIO_OpenDevice())
        logging.info(f'OpenDevice: {"Done!" if self.ID.value else "Wrong!"}')

    def fresh_device_address(self):
        """
        刷新设备地址
        """
        if self.dll.USBIO_I2cAutoGetAddress(self.ID, self.DevAddr):
            self.FdDevAddr = cbyte2int(self.DevAddr._obj.value)
            logging.info(f"Found i2c, the Device Address is {hex(self.FdDevAddr)}")
            self.dll.USBIO_I2cSetConfig(self.ID, self.FdDevAddr, 0x04, 0x00C800C8)  # 400K,200ms time out
        else:
            logging.error("No i2c found, check the hardware, will exit")
            sys.exit()

    def i2cinit(self):
        """
        初始化I2C设备
        """
        logging.info(f'GetGPIOConfig: {self.dll.USBIO_GetGPIOConfig(bc(0), ctypes.byref(bc(255)))}')
        logging.info(f'SetGPIOConfig: {self.dll.USBIO_SetGPIOConfig(bc(0), ctypes.byref(bc(0)))}')
        self.open_i2c_device()
        self.fresh_device_address()

    def write(self, *args):
        """
        写入寄存器
        :param args: 寄存器地址和值，可以是一个元组(地址, 值)，或者一个字典{地址1: 值1, 地址2: 值2, ...}
        :return: 操作成功或失败的字典，包括操作类型、成功或失败、失败的寄存器地址
        """
        output = {
            'Action': 'Write',
            'Success': True,
            'FailedAddresses': []
        }

        # 根据输入参数获取需要写入的寄存器地址和值
        if isinstance(args[0], int):
            data = {args[0]: args[1]}
        elif isinstance(args[0], dict):
            data = args[0]
        else:
            raise ValueError('Unsupported input type for write()')

        # 逐个写入寄存器
        for address, value in data.items():
            # 写入寄存器
            result = self.dll.USBIO_I2cWrite(self.ID, self.FdDevAddr, ctypes.byref(twobc(address)),
                                             self.address_width // 8, ctypes.byref(bc(value)), bc(1))
            # 记录成功或失败
            output['Success'] = output['Success'] and result
            # 如果写入失败，则记录失败的寄存器地址，并输出log
            if not result:
                output['FailedAddresses'].append(hex(address))
                logging.error("Write register {0} fail".format(
                    ("0x%0{0}x".format(self.address_width/4) %address)))
            else:
                logging.info("Write register {0} success".format(
                    ("0x%0{0}x".format(self.address_width/4) %address)))
        return output

    def read(self, *args):
        """
        读取寄存器
        :param args: 寄存器地址，可以是一个整数，表示要读取一个寄存器，或者是一个列表，表示要读取多个
        :return: 操作成功或失败的字典，包括操作类型、成功或失败、寄存器地址、读取到的数据
        """
        output = {
            'Action': 'Read',
            'Success': True,
            'Data': {},
            'FailedAddresses': []
        }

        # 根据输入参数获取需要读取的寄存器列表
        if isinstance(args[0], int):
            addresses = args
        elif isinstance(args[0], list):
            addresses = args[0]
        else:
            raise ValueError('Unsupported input type for read()')

        # 逐个读取寄存器
        for address in addresses:
            # 读取寄存器
            result = self.dll.USBIO_I2cRead(self.ID, self.FdDevAddr, ctypes.byref(twobc(address)),
                                            self.address_width // 8, self.poutdata, bc(1))
            # 获取读到的数据
            val = cbyte2int(self.poutdata._obj.value)
            # 记录成功或失败
            output['Success'] = output['Success'] and result
            # 如果读取失败，则记录失败的寄存器地址，并输出log
            if not result:
                output['FailedAddresses'].append(hex(address))
                logging.error(f"Read register {hex(address)} fail")
            else:
                output['Data'][("0x%0{0}x".format(self.address_width/4) %address)] = hex(val)
                logging.info(f"Read register {hex(address)} value: {hex(val)}")
        return output

    def GPIOset(self, n):
        """
        设置GPIO口状态
        :param n: 要设置的状态（0或1）
        """
        self.dll.USBIO_GPIOWrite(self.ID, bc(n), bc(0))

    def reconnect(self):
        """
        重新连接设备
        """
        self.open_i2c_device()
        self.fresh_device_address()




