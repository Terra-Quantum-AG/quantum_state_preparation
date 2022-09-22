# -*- coding: utf-8 -*-
"""qprepfn.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1YwbdeSHBinW1byU_85CFnoPDYkRaRZ0K
"""

import tensorflow as tf  # tf 2.x
import matplotlib.pyplot as plt

import time

import QGOpt as qgo

import numpy as np

import jax
import tensornetwork as tn

import tt

from qiskit import QuantumCircuit


import quimb
import quimb.tensor as qtn
import cotengra as ctg
from quimb.tensor import MatrixProductState

#from numpy import linalg as LA
#from tt.optimize import tt_min
#from scipy.optimize import rosen
#from qiskit import  assemble, Aer
#from math import sqrt, pi
#import opt_einsum
#from quimb.core import qarray
#from quimb.tensor import MPS_rand_state
#import math

def get_angles(u):
  a = np.angle(u[0,0])
  U2 = u/np.exp(1j*a)
  theta = 2 * np.arccos(U2[0,0])
  lambd = np.angle(-U2[0,1]/np.sin(theta/2))
  phi = np.angle(U2[1,0]/np.sin(theta/2))

  return np.real(theta), phi, lambd

def get_qiskit_circuit(n,Layers,U,cbits=False):
  if cbits:
    qc = QuantumCircuit(n,n)
  else:
    qc = QuantumCircuit(n)
  
  for k in range(n):
    angles = get_angles(U[0][k])
    qc.u(angles[0],angles[1],angles[2],k)

  for l in range(Layers):

    for k in range(n//2):
      qc.cx(2*k,2*k+1)

    for k in range(n):
      angles = get_angles(U[2*l+1][k])
      qc.u(angles[0],angles[1],angles[2],k)

    for k in range(n-1-n//2):
      qc.cx(2*k+1,2*k+2)

    for k in range(n):
      angles = get_angles(U[2*l+2][k])
      qc.u(angles[0],angles[1],angles[2],k)

  return qc

def norm_from_tt(psi_tt):
  norm = psi_tt.norm()
  psi_tt = psi_tt* (1 / norm)
  print(psi_tt.norm())

  return psi_tt , norm

def get_mps_from_func(n, func, eps = 10**(-8), rmax= 10 ):############################################################
  h = 1/(2**n-1)
  x = h * tt.xfun(2,n)
  
  psi_tt = tt.multifuncrs([x], func , eps , rmax , verb = False) 

  psi_tt, norm = norm_from_tt(psi_tt)
  
  return psi_tt, norm

def go_opt(n,Layers,U0,psi_tt,iters=1000,pres=0,contr='greedy',max_repeats=64,max_time=420,peo_tree=[]):
  m = qgo.manifolds.StiefelManifold()
  lr = 0.05 # optimization step size
  opt = qgo.optimizers.RAdam(m, lr)

  u = qgo.manifolds.complex_to_real(U0)
  u = tf.Variable(u)
  err_vs_iter_1 = []

  if contr == 'cotengra':
    if peo_tree == []:
      peo, tree = get_peo_rand(n,Layers,psi_tt,max_repeats=max_repeats,max_time=max_time)
    else:
      peo = peo_tree[0]
      tree = peo_tree[1]
    arr = []
    for i, (p,l,r) in enumerate(tree.traverse()):
      arr.append([x for x in tree.get_inds(l) if x in tree.get_inds(r)])
    edges_inds = list(tree.inputs)

  for _ in range(iters):
    with tf.GradientTape() as tape:
        
        uc = qgo.manifolds.real_to_complex(u)

        nodes, edges = add_scheme(n,Layers,uc)

        b, edges1 = get_nodes_from_tt(n,psi_tt)
        nodes = nodes + b
        for i in range(n):
          edges1[i]^edges[i]
        

        if contr == 'greedy':
          L = tn.contractors.greedy(nodes).get_tensor()
        elif contr == 'cotengra':          
          ALL = prepare_for_contr(n, Layers, edges_inds ,nodes)

          for i in arr:
            L = tn.contract_parallel(ALL[i[0]]).get_tensor()
            for j in i:
              del ALL[j]

 
        L = 1 - tf.math.abs(L)
        L = tf.cast(L, dtype=tf.float64)

    #err_vs_iter_1.append(L.numpy())
    err_vs_iter_1.append(1 - (1 - L.numpy())**2)

    grad = tape.gradient(L, u)
    opt.apply_gradients(zip([grad], [u]))
    
    if err_vs_iter_1[-1] < pres:
      break
    #if len(err_vs_iter_1) > 4:
    #  if abs(err_vs_iter_1[-1] - err_vs_iter_1[-2]) < 10**(-16):
    #    break
  return err_vs_iter_1, u

def get_nodes_from_tt(n,psi_tt,name="tt"):
  a=[]
  e=[]
  for i in range(n):
    an = tn.Node(np.array(psi_tt.to_list(psi_tt)[i],dtype='complex128'),backend="tensorflow",name=name)
    a.append(an)
    e.append(an[1])
  for i in range(n-1):
    a[i][2]^a[i+1][0]
  a[n-1][2]^a[0][0]
  return a, e

def get_initial_MPS(n,name="initial"):
  a=[]
  e=[]
  for i in range(n):
    an = tn.Node(np.array([1,0],dtype='complex128'),backend="tensorflow",name=name)
    a.append(an)
    e.append(an[0])
    

  return a, e

def one_q(n,uc,edges):
  a = []
  e = []
  for i in range(n):
    a.append(connect_onequbit_gate(edges[i],uc[i]))
    e.append(a[i][0])
    
  return a, e

def connect_onequbit_gate(an_node,b):
  bn = tn.Node(b, backend="tensorflow",name="one")
  an_node^bn[1]
  return bn

def connect_cnot(an_node,bn_node):
  cn1 = tn.Node(np.array([[[1., 0.], [0., 0.]],  [[0., 0.], [0., 1.]]],dtype='complex128'), backend="tensorflow",name='cn1')
  cn2 = tn.Node(np.array([[[1., 0.], [0., 1.]],  [[0., 1.], [1., 0.]]],dtype='complex128'), backend="tensorflow",name='cn2')
  an_node^cn1[1]
  bn_node^cn2[2]
  cn1[2]^cn2[1]
  return cn1, cn2

def prepare_for_contr(n, L, edges_inds, nodes):
  ALL = {'0':0}
  fl = 1
  #print(len(nodes))
  for count in range(len(nodes)):
    nod = nodes[count]
    if nod.name == 'initial':
      #print('initial')
      e = list(edges_inds[count])[0]
      ALL[e] = nod[0]

    if nod.name == 'one':
      #print('one')
      ed = list(edges_inds[count])
      for e in ed:
        if e in ALL.keys():
          ALL[e] = nod[1]
        else:
          ALL[e] = nod[0]
    
    elif nod.name == 'cn1':
      #print('cn1')
      ed1 = list(edges_inds[count])
      ed2 = list(edges_inds[count+1])

      for e in ed1:
        if e in ed2:
          ALL[e] = nod[2]
        elif e in ALL.keys():
          ALL[e] = nod[1]
        else:
          ALL[e] = nod[0]

    elif nod.name == 'cn2':
      #print('cn2')
      ed1 = list(edges_inds[count-1])
      ed2 = list(edges_inds[count])

      for e in ed2:
        if e in ed1:
          ALL[e] = nod[1]
        elif e in ALL.keys():
          ALL[e] = nod[2]
        else:
          ALL[e] = nod[0]

    elif nod.name == 'tt':
      
      if fl==1 and n > 1:
        ed0 = list(edges_inds[count])
        ed1 = list(edges_inds[len(nodes)-1])
        for e in ed0:
          if e in ed1:
            ALL[e] = nod[0]

        #  elif e in ALL.keys():
        #    ALL[e] = nod[2]
        #print('tt1')

        fl = 0
      elif fl==0 and  n > 1:
        #print('tt')

        ed = list(edges_inds[count])
        ed2 = list(edges_inds[count-1])
        for e in ed:
          if e in ed2:
            ALL[e] = nod[0]
          #elif e in ALL.keys():
          #  ALL[e] = nod[2]
          #else:
          #  ALL[e] = nod[1]
        
  return ALL

def add_scheme(n,L,uc):
  nodes = []
  a, edges = get_initial_MPS(n)
  nodes = nodes + a

  u0, edges = one_q(n,uc[0],edges)
  nodes = nodes + u0

  l0, edges = add_all_layers(n,L,uc,edges)
  nodes = nodes + l0 
  return nodes, edges

def add_all_layers(n,L,uc,edges0):
  nodes = []
  edges = edges0
  for l in range(L):
    a, edges = add_layer(n,l,uc,edges)
    nodes = nodes + a
  return nodes, edges

def add_layer(n,l,uc,edges0):
  nodes = []
  c0, edges = cnotik_1_new(n,edges0)
  nodes = nodes + c0

  u1, edges = one_q(n,uc[2*l+1],edges)
  nodes = nodes + u1

  c1, edges = cnotik_2_new(n,edges)
  nodes = nodes + c1

  u2, edges = one_q(n,uc[2*l+2],edges)
  nodes = nodes + u2
  return nodes, edges

def cnotik_1_new(n,edges):
  a=[]
  e=[]
  for i in range(n//2):
    for m in connect_cnot(edges[2*i],edges[2*i+1]):
      a.append(m)
      e.append(m[0])
  
  if (n % 2 == 1):
    e.append(edges[n-1])
  return a, e

def cnotik_2_new(n,edges):
  a=[]
  e=[]
  e.append(edges[0])

  for i in range(n-1-n//2):
    for m in connect_cnot(edges[2*i+1],edges[2*i+2]):
      a.append(m)
      e.append(m[0])
    
  if (n % 2 == 0):
    e.append(edges[n-1])
  return a, e

def qiskit_circuit_from_func(func, n, Layers, iters = 200, pres = 0, eps = 10**(-8), rmax = 10):
  m = qgo.manifolds.StiefelManifold()
  U0 = m.random((2*Layers+1,n,2, 2), dtype=tf.complex128)
  psi_tt, norm = get_mps_from_func(n, func, eps = eps, rmax = rmax)
  errs, u = go_opt(n, Layers, U0, psi_tt, iters = iters, pres = pres)
  U = qgo.manifolds.real_to_complex(u)
  qc = get_qiskit_circuit(n,Layers,U.numpy())

  fig , bx = plt.subplots()
  bx.plot(errs)
  bx.set_yscale('log')
  print(errs[-1])

  #fig , ax = plt.subplots()
  #ax.plot(np.abs(psi_tt.full().reshape(2**n,order='F')))

  return qc

def qiskit_circuit_from_tt(psi_tt, n, Layers, U0 = [], iters = 200, pres = 0, eps = 10**(-8), rmax = 10, max_repeats=64,max_time=420, iters_err = True,contr='greedy',peo_tree=[]):
  m = qgo.manifolds.StiefelManifold()
  if U0 == []:
    U0 = m.random((2*Layers+1,n,2, 2), dtype=tf.complex128)
  errs, u = go_opt(n, Layers, U0, psi_tt, iters = iters, pres = pres, max_repeats = max_repeats, max_time=max_time,contr=contr,peo_tree=peo_tree)
  U = qgo.manifolds.real_to_complex(u)
  qc = get_qiskit_circuit(n,Layers,U.numpy())

  if iters_err:
    fig , bx = plt.subplots()
    bx.plot(errs)
    bx.set_yscale('log')
    bx.set_xlabel('iteration')
    bx.set_ylabel('1 - fidelity')

  print("At the last iteration, 1 - fidelity = ",errs[-1])

  #fig , ax = plt.subplots()
  #ax.plot(np.abs(psi_tt.full().reshape(2**n,order='F')))

  return qc, U

def define_tnet_rand(n,L,psi_mps):
  ############Define circuit############
  qcir  =  qtn.Circuit(n)
  

  for m in range(n):
    qcir.apply_gate('U3',np.random.uniform(low=0,high=np.pi),np.random.uniform(low=0,high=2*np.pi),np.random.uniform(low=0,high=np.pi),m)
    

  for l in range(L):

    for m in range(n // 2):
      qcir.apply_gate('CX',2*m,2*m+1)

    for m in range(n):
      qcir.apply_gate('U3',np.random.uniform(low=0,high=np.pi),np.random.uniform(low=0,high=2*np.pi),np.random.uniform(low=0,high=np.pi),m)

    for m in range(n-1-n//2):
      qcir.apply_gate('CX',2*m+1,2*m+2)

    for m in range(n):
      qcir.apply_gate('U3',np.random.uniform(low=0,high=np.pi),np.random.uniform(low=0,high=2*np.pi),np.random.uniform(low=0,high=np.pi),m)
      


  #####################################

  tnet = qcir.psi & psi_mps
  output_inds = []


  #tnet.graph(iterations=20, color=qcir.psi.site_tags, legend=False, figsize=(3, 3))

  return tnet, output_inds

def get_peo_rand(n,L,psi_tt, max_repeats=64, max_time = 420):
  psi_mps = MatrixProductState(psi_tt.to_list(psi_tt),shape= 'lpr')
  tnet, output_inds = define_tnet_rand(n,L,psi_mps)
  opt = ctg.HyperOptimizer(
      methods=['kahypar', 'greedy'],
      max_repeats = max_repeats,
      max_time = max_time,
      progbar=True,
      minimize='flops',
      score_compression=0.5,  # deliberately make the optimizer try many methods 
  )

  info = tnet.contract(all, optimize=opt, get='path-info', output_inds=output_inds)

  peo = opt.path
  tree = opt.get_tree()
  return peo, tree

def divide_mps(psi_tt,n,M):
  MPSs = []
  for m in range(M):
    psi_tt_piece = tt.tensor.from_list((psi_tt.to_list(psi_tt))[m*n//M : (m+1)*n//M]) 

    bb = psi_tt_piece.to_list(psi_tt_piece)

    aa = bb.pop(0)
    bb.insert(0,np.array([aa[-1,:,:]]).reshape(1,2,-1))

    aa = bb.pop(-1)
    bb.append(np.array([aa[:,:,0]]).reshape(-1,2,1))

    psi_tt_piece = tt.tensor.from_list(bb)

    norm = psi_tt_piece.norm()
    psi_tt_piece = psi_tt_piece * (1 / norm)

    MPSs.append(psi_tt_piece)

  return MPSs

def get_initial_point(MPSs,n,Layers,iters=20,print_errs=False):
  m = qgo.manifolds.StiefelManifold()
  M = len(MPSs)
  Us = []
  Errs = []
  for mm in range(M-1):
    
    U0 = m.random((2*Layers+1,n//M,2, 2), dtype=tf.complex128)
    errs, um = go_opt(n//M, Layers, U0, MPSs[mm], iters = iters)
    Um = qgo.manifolds.real_to_complex(um)
    Us.append(Um)
    Errs.append(errs[-1])

  U0 = m.random((2*Layers+1,n - (M-1)*n//M,2, 2), dtype=tf.complex128)
  errs, um = go_opt(n - (M-1)*n//M, Layers, U0, MPSs[M-1], iters = iters)
  Um = qgo.manifolds.real_to_complex(um)
  Us.append(Um)
  Errs.append(errs[-1])

  if print_errs:
    print(Errs)

  return Us
