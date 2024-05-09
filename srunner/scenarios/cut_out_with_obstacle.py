from __future__ import print_function

import sys

from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import (InTriggerDistanceToVehicle,
                                                                               InTriggerDistanceToNextIntersection,
                                                                               DriveDistance,
                                                                               StandStill)

from srunner.tools.scenario_helper import get_waypoint_in_distance, get_location_in_distance_from_wp_previous

from agents.navigation.local_planner import RoadOption

from srunner.scenariomanager.scenarioatomics.atomic_criteria import CollisionTest, DrivenDistanceTest, MaxVelocityTest
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import (InTriggerDistanceToLocation,
                                                                               InTriggerDistanceToNextIntersection,
                                                                               DriveDistance)

from srunner.tools.scenario_helper import (get_crossing_point,
                                           get_geometric_linear_intersection,
                                           generate_target_waypoint_list)
import random
from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (ActorTransformSetter,
                                                                      LaneChange,
                                                                      WaypointFollower,
                                                                      AccelerateToCatchUp)
from srunner.scenariomanager.scenarioatomics.atomic_criteria import CollisionTest
from srunner.scenariomanager.scenarioatomics.atomic_trigger_conditions import InTriggerDistanceToVehicle, DriveDistance
from srunner.scenarios.basic_scenario import BasicScenario

from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (ActorTransformSetter,
                                                                      ActorDestroy,
                                                                      SyncArrival,
                                                                      KeepVelocity,
                                                                      StopVehicle)

from srunner.scenariomanager.scenarioatomics.atomic_behaviors import (ActorTransformSetter,
                                                                      ActorDestroy,
                                                                      StopVehicle,
                                                                      SyncArrival,
                                                                      WaypointFollower)

import math
import py_trees
import carla

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


class CutOutWithObstacle(BasicScenario):
    """
    CutOutWithObstacle scenario:
    ego is following another car on the road
    while the  front car chang the lane because of an obstacle
    The ego vehicle doesn't "see" the obstacle before the lane change of the front car
    """
    timeout = 1200

    def __init__(self, world, ego_vehicles, config, randomize=False, debug_mode=False, criteria_enable=True,
                 timeout=600):
        self.timeout = timeout
        # actor parameters
        # actor's speed
        if config._actor_vel is not None:
            self._velocity = config._actor_vel
        else:
            self._velocity = 5

        # _trigger_distance between ego and actor
        if config._trigger_distance is not None:
            self._trigger_distance = config._trigger_distance
        else:
            self._trigger_distance = 25

        # Initial position of the actor
        if config._start_distance is not None:
            self._start_distance = config._start_distance
        else:
            self._start_distance = 20

        # Initial position of the obstacle
        if config._start_distance2 is not None:
            self._start_distance_obstacle = config._start_distance2
        else:
            self._start_distance_obstacle = 60

        # Record which side the actor cuts out
        self.flag = 0
        self.transform = None
        self.transform_obstacle = None
        #
        self._config = config
        self._wmap = CarlaDataProvider.get_map()
        self._reference_waypoint = self._wmap.get_waypoint(config.trigger_points[0].location)
        self._other_vehicle_distance_driven = 30

        super(CutOutWithObstacle, self).__init__("CutOutWithObstacle",
                                                 ego_vehicles,
                                                 config,
                                                 world,
                                                 debug_mode,
                                                 criteria_enable=criteria_enable)

        if randomize:
            self._velocity = random.randint(20, 60)
            self._trigger_distance = random.randint(10, 40)

    def _calculate_base_transform(self, _start_distance, waypoint):

        lane_width = waypoint.lane_width
        location = waypoint.transform.location
        # self.debug.draw_point((waypoint.previous(20.0)[-1]).transform.location + carla.Location(z=0.5), size=0.5,
        #                       life_time=0)
        offset = {"orientation": 0, "position": 0, "z": 0.6, "k": 0}
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
        location, _ = get_location_in_distance_from_wp(self._reference_waypoint, self._start_distance, False)
        waypoint = self._wmap.get_waypoint(location)
        Flag = waypoint.lane_id
        # Judge if there is a road on the left, cut to the left, otherwise cut to the right
        if waypoint.get_left_lane() is None:
            self.flag = 0
        elif Flag * waypoint.get_left_lane().lane_id > 0:
            self.flag = 1
        lane_width = waypoint.lane_width
        offset = {"orientation": 0, "position": 0, "z": 0, "k": 0}
        position_yaw = waypoint.transform.rotation.yaw + offset['position']
        orientation_yaw = waypoint.transform.rotation.yaw + offset['orientation']
        offset_location = carla.Location(
            offset['k'] * lane_width * math.cos(math.radians(position_yaw)),
            offset['k'] * lane_width * math.sin(math.radians(position_yaw)))
        location += offset_location
        location.z += offset['z']
        self.transform = carla.Transform(location, carla.Rotation(yaw=orientation_yaw))
        first_vehicle_transform = carla.Transform(
            carla.Location(self.transform.location.x,
                           self.transform.location.y,
                           self.transform.location.z - 500),
            self.transform.rotation)
        first_vehicle = CarlaDataProvider.request_new_actor('vehicle.lincoln.mkz2017', first_vehicle_transform)
        first_vehicle.set_simulate_physics(True)
        self.other_actors.append(first_vehicle)

        # put obstacle
        location_obstacle, _ = get_location_in_distance_from_wp(self._reference_waypoint, self._start_distance_obstacle, False)
        waypoint_obstacle = self._wmap.get_waypoint(location_obstacle)
        self.transform_obstacle, _ = self._calculate_base_transform(self._start_distance_obstacle, waypoint_obstacle)
        obstacle_transform = carla.Transform(
            carla.Location(self.transform_obstacle.location.x,
                           self.transform_obstacle.location.y,
                           self.transform_obstacle.location.z - 500),
            self.transform_obstacle.rotation)
        obstacle = CarlaDataProvider.request_new_actor('vehicle.chevrolet.impala', obstacle_transform)
        obstacle.set_simulate_physics(False)
        self.other_actors.append(obstacle)

    def _create_behavior(self):
        # car_visible
        behaviour = py_trees.composites.Sequence("Sequence Behavior")
        car_visible = ActorTransformSetter(self.other_actors[0], self.transform)
        behaviour.add_child(car_visible)

        obstacle_visible = ActorTransformSetter(self.other_actors[1], self.transform_obstacle)
        behaviour.add_child(obstacle_visible)

        # trigger in a certain distance
        just_drive = py_trees.composites.Parallel(
            "DrivingStraight", policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        keepv = WaypointFollower(self.other_actors[0], self._velocity)
        trigger_distance = InTriggerDistanceToVehicle(
            self.other_actors[0], self.other_actors[1], self._trigger_distance)
        just_drive.add_child(keepv)
        just_drive.add_child(trigger_distance)
        behaviour.add_child(just_drive)

        # lane_change
        if self.flag == 1:
            lane_change = LaneChange(
                self.other_actors[0], speed=self._velocity, direction='left', distance_same_lane=0,
                distance_other_lane=40)
            behaviour.add_child(lane_change)
        else:
            lane_change = LaneChange(
                self.other_actors[0], speed=self._velocity, direction='right', distance_same_lane=0,
                distance_other_lane=40)
            behaviour.add_child(lane_change)

        # end condition
        endcondition = py_trees.composites.Parallel("Waiting for end position",
                                                    policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        endcondition.add_child(DriveDistance(self.other_actors[0], self._other_vehicle_distance_driven))
        endcondition.add_child(keepv)

        # build tree
        root = py_trees.composites.Sequence("Behavior", policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        root.add_child(behaviour)
        root.add_child(endcondition)
        root.add_child(ActorDestroy(self.other_actors[0]))
        root.add_child(TimeOut(3))
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
