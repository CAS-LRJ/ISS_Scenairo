from __future__ import print_function

import random
import math
import py_trees
import carla

from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (ActorTransformSetter,
                                                                      LaneChange,
                                                                      WaypointFollower,
                                                                      AccelerateToCatchUp, SetTrafficLightGreen)
from srunner.scenariomanager.scenarioatomics.atomic_criteria import CollisionTest
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import InTriggerDistanceToVehicle, DriveDistance

from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (ActorTransformSetter,
                                                                      ActorDestroy,
                                                                      StopVehicle,
                                                                      SyncArrival,
                                                                      WaypointFollower)
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (ActorTransformSetter,
                                                                      ActorDestroy,
                                                                      AccelerateToVelocity,
                                                                      HandBrakeVehicle,
                                                                      KeepVelocity,
                                                                      StopVehicle)
from srunner.scenariomanager.scenarioatomics.atomic_criteria import CollisionTest
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import (InTriggerDistanceToLocationAlongRoute,
                                                                               InTimeToArrivalToVehicle,
                                                                               DriveDistance)
from srunner.scenariomanager.timer import TimeOut
from srunner.scenarios.basic_scenario import BasicScenario
from srunner.tools.scenario_helper import get_location_in_distance_from_wp


class CutOutWithCutIn(BasicScenario):
    """
    CutInWithObstacle scenario:
    Ego vehicle is driving straight on the road
    Another car is cutting in the road behind a vehicle
    """
    timeout = 1200

    def __init__(self, world, ego_vehicles, config, randomize=False, debug_mode=False, criteria_enable=True,
                 timeout=600):
        """
        Setup all relevant parameters and create scenario
        """
        self.timeout = timeout
        self._config = config

        # Determine where to generate the vehicle
        self.flag = 0
        self._wmap = CarlaDataProvider.get_map()
        # ego's waypoint
        self._reference_waypoint = self._wmap.get_waypoint(config.trigger_points[0].location)

        # actor parameters
        # Travel speed of the actor
        if config._actor_vel is not None:
            self._velocity_cut_out = config._actor_vel
        else:
            self._velocity_cut_out = 6

        if config._actor_vel2 is not None:
            self._velocity_cut_in = config._actor_vel2
        else:
            self._velocity_cut_in = 6

        # trigger_distance
        if config._trigger_distance is not None:
            self._trigger_distance = config._trigger_distance
        else:
            self._trigger_distance = 20

        # Initial position of the actor
        if config._start_distance is not None:
            self._start_distance = config._start_distance
        else:
            self._start_distance = 25

        if config._start_distance2 is not None:
            self._start_distance2 = config._start_distance2
        else:
            self._start_distance2 = 45

        # actor's brake
        if config._brake is not None:
            self.brake = config._brake
        else:
            self.brake = 1.0

        super(CutOutWithCutIn, self).__init__("CutOutWithCutIn",
                                              ego_vehicles,
                                              config,
                                              world,
                                              debug_mode,
                                              criteria_enable=criteria_enable)

    def _calculate_base_transform(self, _start_distance, waypoint):
        """
        Calculate the transform of the actor
        :param (float) _start_distance: Initial position of the actor
        :param (carla.waypoint) waypoint: Position of the reference object
        :return: carla.Transform, carla.Rotation.yaw
        """
        lane_width = waypoint.lane_width
        location, _ = get_location_in_distance_from_wp(waypoint, _start_distance, False)
        waypoint = self._wmap.get_waypoint(location)
        # self.debug.draw_point(waypoint.transform.location + carla.Location(z=0.5), size=0.5, life_time=0)
        offset = {"orientation": 0, "position": 0, "z": 0, "k": 0}
        position_yaw = waypoint.transform.rotation.yaw + offset['position']
        orientation_yaw = waypoint.transform.rotation.yaw + offset['orientation']
        offset_location = carla.Location(
            offset['k'] * lane_width * math.cos(math.radians(position_yaw)),
            offset['k'] * lane_width * math.sin(math.radians(position_yaw)))
        location += offset_location
        location.z += offset['z']
        return carla.Transform(location, carla.Rotation(yaw=orientation_yaw)), orientation_yaw

    def _initialize_actors(self, config):
        """
        Custom initialization
        """
        # Generate other vehicle on the left if it can be placed on the left, or on the right
        waypoint = self._reference_waypoint

        # cut out vehicle
        self.transform, _ = self._calculate_base_transform(self._start_distance, waypoint)
        first_vehicle_transform = carla.Transform(
            carla.Location(self.transform.location.x,
                           self.transform.location.y,
                           self.transform.location.z - 500),
            self.transform.rotation)
        first_vehicle = CarlaDataProvider.request_new_actor('vehicle.tesla.model3', first_vehicle_transform)
        first_vehicle.set_simulate_physics(False)
        self.other_actors.append(first_vehicle)

        if waypoint.get_right_lane() is None or waypoint.get_right_lane().lane_type == carla.LaneType.Sidewalk:
            waypoint = waypoint.get_left_lane()
        elif waypoint.get_right_lane().lane_type == carla.LaneType.Shoulder:
            waypoint = waypoint.get_left_lane()
        elif waypoint.get_right_lane().lane_type == carla.LaneType.Bidirectional:
            waypoint = waypoint.get_left_lane()
        else:
            waypoint = waypoint.get_right_lane()
            self.flag = 1

        # cut in vehicle
        self.transform_obstacle, _ = self._calculate_base_transform(self._start_distance2, waypoint)
        obstacle_transform = carla.Transform(
            carla.Location(self.transform_obstacle.location.x,
                           self.transform_obstacle.location.y,
                           self.transform_obstacle.location.z - 500),
            self.transform_obstacle.rotation)
        obstacle = CarlaDataProvider.request_new_actor('vehicle.carlamotors.carlacola', obstacle_transform)
        obstacle.set_simulate_physics(False)
        self.other_actors.append(obstacle)

    def _create_behavior(self):
        """
        Ego vehicle is driving straight on the road
        Another car is cutting in the road behind a vehicle
        Order of sequence:
        - ActorTransformSetter: spawn car at a visible transform
        - just_drive: Triggered at a certain distance
        - LaneChange: If the vehicle is on the left, cut in from the left, otherwise cut in from the right
        - StopVehicle: emergency brake
        - end condition: wait
        - ActorDestroy: remove the actor
        """
        behaviour = py_trees.composites.Sequence("Sequence Behavior")

        # car_visible
        car_visible = ActorTransformSetter(self.other_actors[0], self.transform)
        car2_visible = ActorTransformSetter(self.other_actors[1], self.transform_obstacle)
        behaviour.add_child(car_visible)
        behaviour.add_child(car2_visible)

        # Triggered at a certain distance
        just_drive = py_trees.composites.Parallel(
            "DrivingStraight", policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        cut_out_keep_v = WaypointFollower(self.other_actors[0], self._velocity_cut_out)
        cut_in_keep_v = WaypointFollower(self.other_actors[1], self._velocity_cut_in)
        trigger_distance = InTriggerDistanceToVehicle(
            self.other_actors[0], self.ego_vehicles[0], self._trigger_distance)
        just_drive.add_child(cut_out_keep_v)
        just_drive.add_child(cut_in_keep_v)
        just_drive.add_child(trigger_distance)

        behaviour.add_child(just_drive)
        behaviour.add_child(SetTrafficLightGreen(self.other_actors[1]))

        # lane_change,If the vehicle is on the left, cut in from the left, otherwise cut in from the right
        if self.flag == 1:
            cutout = LaneChange(
                self.other_actors[0], speed=self._velocity_cut_out, direction='right', distance_same_lane=1,
                distance_other_lane=50)
        else:
            cutout = LaneChange(
                self.other_actors[0], speed=self._velocity_cut_out, direction='left', distance_same_lane=1,
                distance_other_lane=50)

        if self.flag == 0:
            cut_in = LaneChange(
                self.other_actors[1], speed=self._velocity_cut_in, direction='right', distance_same_lane=1,
                distance_other_lane=50)
        else:
            cut_in = LaneChange(
                self.other_actors[1], speed=self._velocity_cut_in, direction='left', distance_same_lane=1,
                distance_other_lane=50)

        lane_change = py_trees.composites.Parallel(
            "lane_change", policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        lane_change.add_child(cutout)
        lane_change.add_child(cut_in)
        behaviour.add_child(lane_change)

        # emergency brake
        stop = StopVehicle(self.other_actors[0], self.brake)
        stop2 = StopVehicle(self.other_actors[1], self.brake)
        behaviour.add_child(stop)
        behaviour.add_child(stop2)

        # end condition
        end_condition = TimeOut(5)

        # build tree
        root = py_trees.composites.Sequence()
        root.add_child(behaviour)
        root.add_child(end_condition)
        root.add_child(ActorDestroy(self.other_actors[0]))
        root.add_child(ActorDestroy(self.other_actors[1]))

        return root

    def _create_test_criteria(self):
        """
        A list of all test criteria is created, which is later used in the parallel behavior tree.
        """
        criteria = []

        collision_criterion = CollisionTest(self.ego_vehicles[0])

        criteria.append(collision_criterion)

        return criteria

    def __del__(self):
        """
        Remove all actors after deletion.
        """
        self.remove_all_actors()
