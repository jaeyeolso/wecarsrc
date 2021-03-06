#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import rospkg
import math
import numpy as np
import matplotlib.pyplot as plt
from sensor_msgs.msg import LaserScan,PointCloud,Imu
from std_msgs.msg import Float64
from vesc_msgs.msg import VescStateStamped
from math import cos,sin,pi,pow,sqrt
from nav_msgs.msg import Odometry,Path
import tf
from morai_msgs.msg import GPSMessage,EgoVehicleStatus
from pyproj import Proj,transform

class LL2UTMConverter:
    def __init__(self, zone=52):
        self.gps_sub = rospy.Subscriber("/gps", GPSMessage, self.navsat_callback)

        self.x,self.y = None, None

        self.proj_UTM = Proj(proj='utm', zone = 52,ellps='WGS84', preserve_units=False)

    def navsat_callback(self,gps_msg):
        self.lat = gps_msg.latitude
        self.lon = gps_msg.longitude

        self.e_o = gps_msg.eastOffset
        self.n_o = gps_msg.northOffset

        self.convertLL2UTM()

    def convertLL2UTM(self):
        xy_zone = self.proj_UTM(self.lon,self.lat)

        self.x = xy_zone[0] - self.e_o
        self.y = xy_zone[1] - self.n_o

class CMDParser:
    def __init__(self):
        self.speed_sub = rospy.Subscriber('/sensors/core',VescStateStamped,self.status_callback)

        self.steer_sub = rospy.Subscriber('/sensors/servo_position_command',Float64,self.steer_callback)

        self.u = np.zeros((2,))

    def status_callback(self,msg):
        self.u[0] = msg.state.speed
    
    def steer_callback(self,msg):
        self.u[1] = np.deg2rad((msg.data-0.53)*(-22))

class ExtendedKalmanFilter:
    def __init__(self,dt=0.05, l_vehicle=0.5, tau=0.1, K=float(3.6*6/7500)):
        self.dt=dt
        self.l = l_vehicle
        self.tau = tau
        self.K= K

        self.X = np.array([-500,-500,0,0], dtype = float).reshape([-1,1])
        self.P = np.diag([0,0,0.2,0.2])

        self.Q = self.dt*np.diag([0,0,0.0,0.2])
        self.R = np.diag([0.01, 0.01])/self.dt

        self.H = np.array([
            [1,0,0,0],
            [0,1,0,0]
        ])

        self.esti_pub = rospy.Publisher('/estimation',EgoVehicleStatus,queue_size=1)

    def prediction_step(self,u):
        #print(u)
        dX_pre = np.zeros((4,1),dtype=float)

        dX_pre[0,:] = self.X[3,:] * np.cos(self.X[2,:])
        dX_pre[1,:] = self.X[3,:] * np.sin(self.X[2,:])
        dX_pre[2,:] = self.X[3,:] * np.tan(u[1])/self.l
        dX_pre[3,:] = (1/self.tau)*(-self.X[3,:] + self.K * u[0])

        self.calc_F(u)

        self.X = self.X + (self.dt*dX_pre)

        if self.X[2,:] < -np.pi:
            self.X[2,:] = self.X[2,:] + 2*np.pi
        elif self.X[2,:] > np.pi:
            self.X[2,:] = self.X[2,:] - 2*np.pi
        else:
            pass

        self.P = self.F.dot(self.P).dot(self.F.T) + self.Q

    def correction_step(self,Z):
        K = self.P.dot(self.H.T).dot(np.linalg.inv(self.H.dot(self.P).dot(self.H.T)+self.R))

        Y = self.H.dot(self.X)

        self.X += K.dot(Z-Y)

        self.P -= K.dot(self.H).dot(self.P)

    def calc_F(self,u):
        self.F = np.identity(4,dtype = float)
        self.F[0,2] += -self.dt* self.X[3,:] * np.sin(self.X[2,:])
        self.F[0,3] += self.dt * np.cos(self.X[2,:])
        self.F[1,2] += self.dt * self.X[3,:] * np.cos(self.X[2,:])
        self.F[1,3] += self.dt * np.sin(self.X[2,:])
        self.F[2,3] += self.dt * np.tan(u[1])/self.l
        self.F[3,3] += self.dt / (-self.tau)

    def pub_estimated_state(self):

        esti_msg = EgoVehicleStatus()

        esti_msg.pose_x = self.X[0,:]
        esti_msg.pose_y = self.X[1,:]
        esti_msg.heading = self.X[2,:]
        esti_msg.velocity = self.X[3,:]

        self.esti_pub.publish(esti_msg)

if __name__ == "__main__":
    rospy.init_node('EKF_estimator', anonymous = True)

    rate = rospy.Rate(20)

    loc_sensor = LL2UTMConverter()
    ekf = ExtendedKalmanFilter(dt=0.05)

    u_parser = CMDParser()

    while not rospy.is_shutdown():
        if loc_sensor.x is not None and loc_sensor.y is not None:
            u = u_parser.u

            ekf.prediction_step(u)

            z = np.array([loc_sensor.x, loc_sensor.y]).reshape([-1,1])

            ekf.correction_step(z)

            ekf.pub_estimated_state()
        else:
            pass
        rate.sleep()

    

