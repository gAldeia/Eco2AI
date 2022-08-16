import os
import time
import platform
from typing import Type
import pandas as pd
import requests
import psutil
import string
import uuid
import numpy as np
import warnings
from re import sub
import json
from pkg_resources import resource_stream
import sys
from apscheduler.schedulers.background import BackgroundScheduler

from eco2ai.tools.tools_gpu import GPU, all_available_gpu
from eco2ai.tools.tools_cpu import CPU, all_available_cpu
from eco2ai.tools.tools_ram import RAM


FROM_mWATTS_TO_kWATTH = 1000*1000*3600
FROM_kWATTH_TO_MWATTH = 1000


class FileDoesNotExists(Exception):
    pass


class NotNeededExtension(Exception):
    pass


def set_params(**params):
    """
        This function sets default Tracker attributes values to internal file:
        project_name = ...
        experiment_description = ...
        file_name = ...
        measure_period = ...
        pue = ...
        
        Parameters
        ----------
        params: dict
            Dictionary of Tracker parameters: project_name, experiment_description, file_name. 
            Other parameters in dictionary are ignored
        
        Returns
        -------
        No return

    """
    dictionary = dict()
    filename = resource_stream('eco2ai', 'data/config.txt').name
    for param in params:
        dictionary[param] = params[param]
    if "project_name" not in dictionary:
        dictionary["project_name"] = "default project name"
    if "experiment_description" not in dictionary:
        dictionary["experiment_description"] = "default experiment description"
    if "file_name" not in dictionary:
        dictionary["file_name"] = "emission.csv"
    if "measure_period" not in dictionary:
        dictionary["measure_period"] = 10
    if "pue" not in dictionary:
        dictionary["pue"] = 1
    with open(filename, 'w') as json_file:
        json_file.write(json.dumps(dictionary))


def get_params():
    """
        This function returns default Tracker attributes values:
        project_name = ...
        experiment_description = ...
        file_name = ...
        measure_period = ...
        pue = ...
        More complete information about attributes can be seen in Tracker class
        
        Parameters
        ----------
        No parameters
        
        Returns
        -------
        params: dict
            Dictionary of Tracker parameters: project_name, experiment_description, file_name, measure_period and pue

    """
    filename = resource_stream('eco2ai', 'data/config.txt').name
    if not os.path.isfile(filename):
        with open(filename, "w"):
            pass
    with open(filename, "r") as json_file:
        if os.path.getsize(filename):
            dictionary = json.loads(json_file.read())
        else:
            dictionary = {
                "project_name": "Deafult project name",
                "experiment_description": "no experiment description",
                "file_name": "emission.csv",
                "measure_period": 10,
                "pue": 1,
                }
    return dictionary




def define_carbon_index(
    emission_level=None, 
    alpha_2_code=None
):
    """
        This function get an IP of user, defines country and region.
        Then, it searchs user emission level by country and region in the emission level database.
        If there is no certain country, then it returns worldwide constant. 
        If there is certain country in the database, but no certain region, 
        then it returns average country emission level. 
        User can define own emission level and country, using the alpha2 country code.

        Parameters
        ----------
        emission_level: float
            User specified emission level value.
            emission_level is the mass of CO2 in kilos, which is produced  per every MWh of consumed energy.
            Default is None
        alpha_2_code: str
            User specified country code
            User can search own country code here: https://www.iban.com/country-codes
            Default is None
        
        Returns
        -------
        tuple: tuple
            A tuple, where the first element is float emission value
            and the second element is a string containing a country 
            if user specified it or country and region in other case

    """
    carbon_index_table_name = resource_stream('eco2ai', 'data/carbon_index.csv').name
    if alpha_2_code is None:
        ip_dict = eval(requests.get("https://ipinfo.io/").content.decode('ascii'))
        country = ip_dict['country']
        region = ip_dict['region']
    else:
        country = alpha_2_code
        region = None
    if emission_level is not None:
        return (emission_level, f'({country}/{region})') if region is not None else (emission_level, f'({country})')
    data = pd.read_csv(carbon_index_table_name)
    result = data[data['alpha_2_code'] == country]
    if result.shape[0] < 1:
        result = data[data['country'] == 'World']
    if result.shape[0] > 1:
        if data[data['region'] == region].shape[0] > 0:
            result = data[data['region'] == region]
        else: 
            result = result[result['region'] == 'Whole country']
    result = result.values[0][-1]
    return (result, f'{country}/{region}') if region is not None else (result, f'{country}')


def is_file_opened(
    needed_file
):
    """
        This function checks if given file is opened in any python or jupyter process
        
        Parameters
        ----------
        needed_file: str
            Name of file that is going to be checked 
        
        Returns
        -------
        result: bool
            True if file is opened in any python or jupyter process
            

    """
    result = False
    needed_file = os.path.abspath(needed_file)
    python_processes = []
    for proc in psutil.process_iter():
        try:
            pinfo = proc.as_dict(attrs=["name", "cpu_percent", "pid"])
            if "python" in pinfo["name"].lower() or "jupyter" in pinfo["name"].lower():
                python_processes.append(pinfo["pid"])
                flist = proc.open_files()
                if flist:
                    for nt in flist:
                        if needed_file in nt.path:
                            result = True
        except:
            pass
    return result


class Tracker:
    """
        This class calculates CO2 emissions during CPU or GPU calculations 
        In order to calculate CPU & GPU power consumption correctly you should create the 'Tracker' before any CPU or GPU usage
        It is recommended to create a new “Tracker” object per every new calculation.
        
        Example
        ----------
        import eco2ai.Tracker
        tracker = eco2ai.Tracker()

        tracker.start()

        *your CPU and GPU calculations*
        
        tracker.stop()

    """
    def __init__(self,
                 project_name=None,
                 experiment_description=None,
                 file_name=None,
                 measure_period=10,
                 emission_level=None,
                 alpha_2_code=None,
                 pue=1,
                 encode_file=None,
                 ):
        """
            This class method initializes Thacker object and creates fields of class object
            
            Parameters
            ----------
            project_name: str
                Specified by user project name.
                The default is None
            experiment_description: str 
                Specified by user experiment description.
                The default is None
            file_name: str
                Name of file to save the the results of calculations.
                The default is None
            measure_period: float
                Period of power consumption measurements in seconds.
                The more period the more time between measurements.
                The default is 10
            emission_level: float
                The mass of CO2 in kilos, which is produced  per every MWh of consumed energy.
                The default is None
            alpha_2_code: str
                User specified country code.
                User can search own country code here: https://www.iban.com/country-codes
                Default is None
            pue: float
                Power utilization efficiency. 
                It is ration of the total 'facility power' and 'IT equipment energy consumption'. 
                PUE is a measure of a data center power efficiency.
                This parameter will be very essential during calculations using data centres facilities.
                The default is 1.
            encode_file: str
                If this parameter is not None, results of calculations will be encoded
                and the results will be writen to file.
                If this parameter == True encoded data will be written to file "encoded_" + value of file_name parameter.
                So, default name of file with encoded data will be "encoded_emission.csv"
                If this parameter is of str type, then name of file with encoded data will be value of encode_file parameter.
                The default is None. 
            
            Returns
            -------
            Tracker: Tracker
                Object of class Tracker

        """
        warnings.warn(
    message="""
    If you use a VPN, you may have problems with identifying your country by IP.
    It is recommended to disable VPN or
    manually install the ISO-Alpha-2 code of your country during initialization of the Tracker() class.
    You can find the ISO-Alpha-2 code of your country here: https://www.iban.com/country-codes
    """
)
        if (type(measure_period) == int or type(measure_period) == float) and measure_period <= 0:
            raise ValueError("\'measure_period\' should be positive number")
        if encode_file is not None:
            if type(encode_file) is not str and not (encode_file is True):
                raise TypeError(f"'encode_file' parameter should have str type, not {type(encode_file)}")
            if type(encode_file) is str and not encode_file.endswith('.csv'):
                raise NotNeededExtension(f"'encode_file' name need to be with extension \'.csv\'")
        self._params_dict = get_params()
        self.project_name = project_name if project_name is not None else self._params_dict["project_name"]
        self.experiment_description = experiment_description if experiment_description is not None else self._params_dict["experiment_description"]
        self.file_name = file_name if file_name is not None else self._params_dict["file_name"]
        self._measure_period = measure_period if measure_period is not None else self._params_dict["measure_period"]
        self._pue = pue if pue is not None else self._params_dict["pue"]
        self.get_set_params(self.project_name, self.experiment_description, self.file_name, self._measure_period, self._pue)

        self._emission_level, self._country = define_carbon_index(emission_level, alpha_2_code)
        self._scheduler = BackgroundScheduler(job_defaults={'max_instances': 10}, misfire_grace_time=None)
        self._start_time = None
        self._cpu = None
        self._gpu = None
        self._ram = None
        self._id = None
        self._consumption = 0
        self._encode_file=encode_file if encode_file != True else "encoded_"+file_name
        self._os = platform.system()
        if self._os == "Darwin":
            self._os = "MacOS"
        # self._mode == "first_time" means that the Tracker is just initialized
        # self._mode == "run time" means that CO2 tracker is now running
        # self._mode == "shut down" means that CO2 tracker is stopped
        self._mode = "first_time"
    

    def get_set_params(
        self, 
        project_name=None, 
        experiment_description=None, 
        file_name=None,
        measure_period=None,
        pue=None
        ):
        """
            This function returns default Tracker attributes values:
            project_name = ...
            experiment_description = ...
            file_name = ...
            measure_period = ...
            pue = ...
            
            Parameters
            ----------
            project_name: str
                Specified by user project name.
                The default is None
            experiment_description: str 
                Specified by user experiment description.
                The default is None
            file_name: str
                Name of file to save the the results of calculations.
                The default is None
            measure_period: float
                Period of power consumption measurements in seconds.
                The more period the more time between measurements.
                The default is None
            pue: float
                Power utilization efficiency. 
                It is ration of the total 'facility power' and 'IT equipment energy consumption'. 
                PUE is a measure of a data center power efficiency.
                This parameter will be very essential during calculations using data centres facilities.
                The default is None

            Returns
            -------
            dictionary: dict


        """
        dictionary = dict()
        if project_name is not None:
            dictionary["project_name"] = project_name
        else: 
            dictionary["project_name"] = "default project name"
        if experiment_description is not None:
            dictionary["experiment_description"] = experiment_description
        else:
            dictionary["experiment_description"] = "default experiment description"
        if file_name is not None:
            dictionary["file_name"] = file_name
        else:
            dictionary["file_name"] = "emission.csv"
        if measure_period is not None:
            dictionary["measure_period"] = measure_period
        else:
            dictionary["measure_period"] = 10
        if pue is not None:
            dictionary["pue"] = pue
        else:
            dictionary["pue"] = 1
        set_params(**dictionary)

        return dictionary


    def consumption(self):
        """
            This class method returns consumption

            Parameters
            ----------
            No parameters

            Returns
            -------
            consumption: float
                Power consumption of every device in a system.

        """
        return self._consumption
    

    def id(self):
        """
            This class method returns the Tracker id

            Parameters
            ----------
            No parameters

            Returns
            -------
            id: str
                The Tracker's id. id is random UUID

        """
        return self._id


    def emission_level(self):
        """
            This class method returns emission level

            Parameters
            ----------
            No parameters

            Returns
            -------
            emission_level: float
                emission_level is the mass of CO2 in kilos, which is produced  per every MWh of consumed energy.
                
        """
        return self._emission_level
    

    def measure_period(self):
        """
            This class method returns measure period of Tracker

            Parameters
            ----------
            No parameters

            Returns
            -------
            measure_period: float
                Period of power consumption measurements.
                The more period the more time between measurements.
                The default is 10
                
        """
        return self._measure_period


    def _write_to_csv(
        self,
        ):
        """
            This class method writes to .csv file calculation results.
            Results is a table with the following columns:
                project_name
                experiment_description(model type etc.)
                start_time
                duration(s)
                power_consumption(kWTh)
                CO2_emissions(kg)
                CPU_name
                GPU_name
                OS
                region/country

            Parameters
            ----------
            No parameters

            Returns
            -------
            attributes_dict: dict
                Dictionary with all the attibutes that should be written to .csv file
                
        """
        # if user used older versions, it may be needed to upgrade his .csv file
        # but after all, such verification should be deleted
        # self.check_for_older_versions()
        attributes_dict = dict()
        attributes_dict["id"] = [self._id]
        attributes_dict["project_name"] = [f"{self.project_name}"]
        attributes_dict["experiment_description"] = [f"{self.experiment_description}"]
        attributes_dict["epoch"] = [f"N\A"]
        attributes_dict["start_time"] = [f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._start_time))}"]
        attributes_dict["duration(s)"] = [f"{time.time() - self._start_time}"]
        attributes_dict["power_consumption(kWTh)"] = [f"{self._consumption}"]
        attributes_dict["CO2_emissions(kg)"] = [f"{self._consumption * self._emission_level / FROM_kWATTH_TO_MWATTH}"]
        attributes_dict["CPU_name"] = [f"{self._cpu.name()}/{self._cpu.cpu_num()} device(s), TDP:{self._cpu.tdp()}"]
        attributes_dict["GPU_name"] = [f"{self._gpu.name()} {self._gpu.gpu_num()} device(s)"]
        attributes_dict["OS"] = [f"{self._os}"]
        attributes_dict["region/country"] = [f"{self._country}"]
        attributes_dict["cost"] = [f"N\A"]

        if not os.path.isfile(self.file_name):
            while True:
                if not is_file_opened(self.file_name):
                    open(self.file_name, "w").close()
                    tmp = open(self.file_name, "w")
                    pd.DataFrame(attributes_dict).to_csv(self.file_name, index=False)
                    tmp.close()
                    break
                else: 
                    time.sleep(0.5)
                
        else:
            while True:
                if not is_file_opened(self.file_name):
                    tmp = open(self.file_name, "r")

                    attributes_dataframe = pd.read_csv(self.file_name)
                    if list(attributes_dataframe.columns) != list(attributes_dict.keys()):
                        attributes_dataframe = self._update_to_new_version(attributes_dataframe, list(attributes_dict.keys()))
                    # constructing an array of attributes
                    attributes_array = []
                    for element in attributes_dict.values():
                        attributes_array += element
                    
                    if attributes_dataframe[attributes_dataframe['id'] == self._id].shape[0] == 0:
                        attributes_dataframe.loc[attributes_dataframe.shape[0]] = attributes_array
                    else:
                        row_index = attributes_dataframe[attributes_dataframe['id'] == self._id].index.values[0]
                        attributes_dataframe.loc[row_index] = attributes_array
                    attributes_dataframe.to_csv(self.file_name, index=False)

                    tmp.close()
                    break
                else: 
                    time.sleep(0.5)
        self._mode = "run time"
        return attributes_dict


    def _update_to_new_version(self, attributes_dataframe, new_columns):
        """
            This class method is a function, that updates dataframe to newer versions: adds new columns etc

            Parameters
            ----------
            attributes_dataframe: pd.DataFrame
                Dataframe to update
            new_columns: list
                New columns which should be contained in updated dataframe

            Returns
            -------
           dataframe: pd.DataFrame
            Updated dataframe.
        
        """
        current_columns = list(attributes_dataframe.columns)
        # print("1: ", new_columns, current_columns)
        for column in new_columns:
            if column not in current_columns:
                attributes_dataframe[column] = "N\A"
        attributes_dataframe = attributes_dataframe[new_columns]

        return attributes_dataframe


    def _func_for_sched(self,):
        """
            This class method is a function, that puts in a scheduler and runs periodically during Thacker work.
            It calculates CPU, GPU and RAM power consumption and writes results to a .csv file.

            Parameters
            ----------
            No parameters

            Returns
            -------
            No returns
        
        """
        cpu_consumption = self._cpu.calculate_consumption()
        ram_consumption = self._ram.calculate_consumption()
        if self._gpu.is_gpu_available:
            gpu_consumption = self._gpu.calculate_consumption()
        else:
            gpu_consumption = 0
        tmp_comsumption = 0
        tmp_comsumption += cpu_consumption
        tmp_comsumption += gpu_consumption
        tmp_comsumption += ram_consumption
        tmp_comsumption *= self._pue
        self._consumption += tmp_comsumption
        self._write_to_csv()
        # self._consumption = 0
        # self._start_time = time.time()
        if self._mode == "shut down":
            self._scheduler.remove_job("job")
            self._scheduler.shutdown()


    def start(self):
        """
            This class method starts the Tracker work. It initializes fields of CPU and GPU classes,
            initializes scheduler, put the self._func_for_sched function into it and starts its work.

            Parameters
            ----------
            No parameters

            Returns
            -------
            No returns
        
        """
        if self._start_time is not None:
            try:
                self._scheduler.remove_job("job")
                self._scheduler.shutdown()
            except:
                pass
            self._scheduler = BackgroundScheduler(job_defaults={'max_instances': 10}, misfire_grace_time=None)
        self._cpu = CPU()
        self._gpu = GPU()
        self._ram = RAM()
        self._id = str(uuid.uuid4())
        self._mode = "first_time"
        self._start_time = time.time()
        self._scheduler.add_job(self._func_for_sched, "interval", seconds=self._measure_period, id="job")
        self._scheduler.start()


    def stop(self, ):
        """
            This class method stops the Tracker work, removes self._func_for_sched from the scheduler
            and stops its work, it also writes to file final calculation results.

            Parameters
            ----------
            No parameters

            Returns
            -------
            No returns
        
        """
        if self._start_time is None:
            raise Exception("Need to first start the tracker by running tracker.start()")
        self._scheduler.remove_job("job")
        self._scheduler.shutdown()
        self._func_for_sched() 
        attributes_dict = self._write_to_csv()
        if self._encode_file is not None:
            self._func_for_encoding(attributes_dict)
        self._consumption = 0
        self._mode = "shut down"


    
    def _func_for_encoding(self, attributes_dict):
        """
            This function encodes all calculated data and attributes and writes it to file.
            File name depenвs on 'encode_file' parameter. 
            More details can be seen in 'encode_file' parameter description in Tracker class.

            Parameters
            ----------
            attributes_dict: dict
                Dictionary with all the attibutes that should be written to .csv file

            Returns
            -------
            No returns
        
        """

        for key in attributes_dict.keys():
            attributes_dict[key] = [encode(str(attributes_dict[key][0]))]

        if not os.path.isfile(self._encode_file):
            while True:
                if not is_file_opened(self._encode_file):
                    open(self._encode_file, "w").close()
                    tmp = open(self._encode_file, "r")

                    pd.DataFrame(attributes_dict).to_csv(self._encode_file, index=False)

                    tmp.close()
                    break
                else: 
                    time.sleep(0.5)
        
        else:
            while True:
                if not is_file_opened(self._encode_file):
                    tmp = open(self._encode_file, "r")

                    attributes_dataframe = pd.read_csv(self._encode_file)
                    attributes_array = []
                    for element in attributes_dict.values():
                        attributes_array += element
                    attributes_dataframe.loc[attributes_dataframe.shape[0]] = attributes_array
                    attributes_dataframe.to_csv(self._encode_file, index=False)

                    tmp.close()
                    break
                else: 
                    time.sleep(0.5)


def available_devices():
    """
        This function prints all the available CPU & GPU devices

        Parameters
        ----------
        No paarameters

        Returns
        -------
        No returns        
    
    """
    all_available_cpu()
    all_available_gpu()
    # need to add RAM


def track(func):
    """
        This function is a decorator, that modifies any function by creating Tracker object and 
        running Tracker.start() in the beginning of the function and Tracker.stop() in the end of function.

        Parameters
        ----------
        func: function
            Any function user wants to modify.

        Returns
        -------
        No returns. 
    
    """
    def inner(*args):
        tracker = Tracker()
        tracker.start()
        try:
            returned = func(*args)
        except Exception:
            tracker.stop()
            del tracker
            raise Exception
        tracker.stop()
        del tracker
        return returned
    return inner


def calculate_money(
    kwh_price,
    filename,
    project_name='all',
    experiment_description=None
):
    """
        This function calculates amount of money according to price of one kilo-watt-hour.

        Parameters
        ----------
        kwh_price: float
            Price of one kilo-watt-hour of energy.
        filename: str
            Name of file the user wants to analyse.
        project_name: str
            Name of project for which the user wants to calculate money.
            Default is 'all'.
        experiment_description:
            Experiment description of the project for which the user wants to calculate money.
            Default is None. None means user wants to analyse all that is connected to the specified project name.

        Returns
        -------
        
    
    """
    if not os.path.exists(filename):
        raise FileDoesNotExists(f'File \'{filename}\' does not exist')
    if not filename.endswith('.csv'):
        raise NotNeededExtension('File need to be with extension \'.csv\'')
    df = pd.read_csv(filename)
    if project_name != 'all':
        df = df[df['project_name'] == project_name]
    if experiment_description is not None:
        df = df[df['experiment_description(model type etc.)'] == experiment_description]
    if df.shape[0] == 0:
        warnings.warn(
            '''
            There is no any projects with your specified project_name and experiment_description arguments
            '''
        )
        
    consumption = df['power_consumption(kWTh)'].values
    consumption = consumption.sum()
    
    return consumption * kwh_price


def summary(
    filename,
    kwh_price=None,
    write_to_file=False,
):
    """
        This function makes a summary of the specified .csv file. 
        It sums up duration, power consumption and CO2 emissions for every project separately
        and for all the projects together. 
        For every sum up it makes separate line in a summary dataframe with the following columns:
            project_name
            total duration(s)
            total power_consumption(kWTh)
            total CO2_emissions(kg)
            total electricity price (only if 'kwh_price' parameter is not None)
        Number of lines equals number of projects + 1, as the last line is summary for all the projects.
        
        Parameters
        ----------
        filename: str
            Name of file the user wants to analyse.
        kwh_price: float
            Price of one kilo-watt-hour of energy.
            Default is None,
        write_to_file: str
            If this parameter is not None the resultant dataframe will be written to file with name of this parameter.
            For example, is write_to_file == 'total_summary_project_1.csv', 
            then resultant summary dataframe will be written to file 'total_summary_project_1.csv'.
            Default is None

        Returns
        -------
        summary_data: pandas.DataFrame
            The result dataframe, containing a summary for every project separately and full summary.
            For every sum up it makes separate line in a result dataframe with the following columns:
                project_name
                total duration(s)
                total power_consumption(kWTh)
                total CO2_emissions(kg)
                total electricity price (only if 'kwh_price' parameter is not None)
    
    """
    if not os.path.exists(filename):
        raise FileDoesNotExists(f'File \'{filename}\' does not exist')
    if not filename.endswith('.csv'):
        raise NotNeededExtension('File need to be with extension \'.csv\'')
    df = pd.read_csv(filename)
    projects = np.unique(df['project_name'].values)
    summary_data = []
    columns = [
            'project_name', 
            'total duration(s)', 
            'total power_consumption(kWTh)', 
            'total CO2_emissions(kg)',
        ]
    summ = np.zeros(3)
    for project in projects:
        values = df[df['project_name'] == project][
                ['duration(s)', 'power_consumption(kWTh)', 'CO2_emissions(kg)']
            ].values.sum(axis=0)
        summ += values
        values = list(values)
        values.insert(0, project)
        if kwh_price is not None:
            values.append(values[2] * kwh_price)
        summary_data.append(values)
        
    summ = list(summ)
    summ.insert(0, 'All the projects')
    if kwh_price is not None:
        summ.append(summ[2] * kwh_price)
        columns.append('total electricity price')
    summary_data.append(summ)
    summary_data = pd.DataFrame(
        summary_data,
        columns=columns
    )
    if write_to_file:
        summary_data.to_csv(write_to_file)
    return summary_data


def encode(f_string):
    """
        This function encodes given string.

        Parameters
        ----------
        f_string: str
            A string user wants to encode

        Returns
        -------
        encoded_string: str
            Resultant encoded string
    
    """
    n=5
    symbols = string.printable[:95] + 'йцукенгшщзхъфывапролджэячсмитьбюёЁЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ'
    symbols = symbols.replace(',', '')
    symbols = symbols.replace('\"', '')
    symbols = symbols.replace('\'', '')
    s = ''
    for i in range(0,int(len(symbols)/2)):
        s += symbols[i] + symbols[i+int(len(symbols)/2)]
    symbols = s
    
    encoded_string = ""
    for letter in f_string:
        try:
            index = symbols.index(letter)
            encoded_string += symbols[index+n]
        except:
            encoded_string += letter
    return encoded_string


def encode_dataframe(values):
    """
        This function encodes every value of a two-dimentional array

        Parameters
        ----------
        values: array
            Array, which values user wants to encode

        Returns
        -------
        values: array
            Resultant encoded array
        
    
    """
    values = values.astype(str)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            values[i][j] = encode(values[i][j])
    return values