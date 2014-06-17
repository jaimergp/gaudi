###########################################################
# CHIMERA SCRIPT
# Rotate selected bonds, find clashes and H bonds
# By Jaime RG <jaime.rogue@gmail.com>, in UAB
###########################################################

## VERSION 7
# Implement genetic algorithm

# Chimera
import chimera, Rotamers, SwapRes, Matrix as M
# Python
import random, numpy, deap, sys, math
from deap import creator, tools, base, algorithms
import yaml
# Custom
import gaudi
from gaudi.utils import box

### CUSTOM FUNCTIONS

def evaluate(ind, close=True, hidden=False, draw=False):

	ligand = ligands[ind['ligand']]
	chimera.openModels.add([ligand.mol], shareXform=True, hidden=hidden)
	box.pseudobond_to_bond(ligand.mol)
	if 'rotable_bonds' in ind:
		for alpha, br in zip(ind['rotable_bonds'], ligand.rotatable_bonds):
			try: 
				if all([a.idatmType in ('C2', 'N2') for a in br.bond.atoms]):
					alpha = 0 if alpha<180 else 180
				br.adjustAngle(alpha - br.angle, br.rotanchor)
			except AttributeError: # A null bondrot was returned -> non-rotatable bond
				continue

	if 'xform' in ind:
		ligand.mol.openState.xform = M.chimera_xform(M.multiply_matrices(*ind['xform']))

	if 'rotamers' in ind:
		lib_dict = { 'Dynameomics': 'DYN', 'Dunbrack': 'DUN'}
		ind.parsed_rotamers = []
		if 'mutamers' in ind:
			aas = [ AA[i] for i in ind['mutamers'] ]
		else:
			aas = [ r.type for r in residues ]
		for res, rot, mut in map(None, residues, ind['rotamers'], aas):
			try:
				rotamers = Rotamers.getRotamers(res, resType=mut,
												lib=cfg.rotamers.library.title())[1]
				rot_to_use = rotamers[rot]
				chis = rot_to_use.chis
				Rotamers.useRotamer(res, [rot_to_use])
			except Rotamers.NoResidueRotamersError: # ALA, GLY...
				if 'mutamers' in ind:
					SwapRes.swap(res, mut, bfactor=None)
					chis = []
			except IndexError: #use last available
				rot_to_use = rotamers[-1]
				chis = rot_to_use.chis
				Rotamers.useRotamer(res, [rot_to_use] )
			finally:
				ind.parsed_rotamers.append(' '.join(['.'.join([str(res.id.position), 
																res.id.chainId]),
												lib_dict[cfg.rotamers.library.title()],
												mut] + map(str,chis)))
	ligand_env.clear()
	ligand_env.add(ligand.mol.atoms)
	ligand_env.merge(chimera.selection.REPLACE,
					chimera.specifier.zone( ligand_env, 'atom', None, 10.0,
											[protein,ligand.mol]))
	score, draw_list = [], {}
	for obj in cfg.objectives:
		if obj.type == 'hbonds':
			hbonds = gaudi.score.chem.hbonds(
						[protein, ligand.mol], cache=False, test=ligand_env.atoms(),
						sel=[ a for a in ligand.mol.atoms if a not in ("C", "CA", "N", "O") ],
						dist_slop=obj.distance_tolerance, angle_slop=obj.angle_tolerance)
			score.append(len(hbonds))
			draw_list['hbonds'] = hbonds
			if hasattr(obj, 'targets') and len(obj.targets):
				hb_targets = box.atoms_by_serial(*obj.targets, atoms=protein.atoms)
				hb_targets_num = [ha for hb in hbonds for ha in hb if ha in hb_targets]
				score.append(len(hb_targets_num))
		
		elif obj.type == 'contacts':
			if cfg.ligand.type == 'blocks':
				ligand_atoms = [a for a in ligand.mol.atoms if a.serialNumber > 3]
			else:
				ligand_atoms = ligand.mol.atoms
			contacts, num_of_contacts, positive_vdw, negative_vdw = \
				gaudi.score.chem.clashes(atoms=ligand_atoms, test=ligand_env.atoms(), 
										intraRes=True, clashThreshold=obj.threshold, 
										hbondAllowance=obj.threshold_h, parse=True,
										parse_threshold=obj.threshold_c)
			if obj.which == 'clashes':
				clashscore = sum(abs(a[3]) for a in negative_vdw)/2
				if clashscore > obj.cutoff and close:
					chimera.openModels.remove([ligand.mol])
					return [-1000*w for w in weights]
				score.append(clashscore)
				draw_list['negvdw'] = negative_vdw
			elif obj.which == 'hydrophobic':
				score.append(sum(1-a[3] for a in positive_vdw)/2)
				draw_list['posvdw'] = positive_vdw

		elif obj.type == 'distance':
			probes = []
			for p in obj.probes:
				if p == 'last':
					probes.append(ligand.acceptor)
					continue
				probes.extend(box.atoms_by_serial(p), atoms=ligand.mol.atoms)
			dist_target, = box.atoms_by_serial(obj.target, atoms=protein.atoms)
			dist = gaudi.score.target.distance(probes, dist_target, obj.threshold, 
						obj.threshold2)
			score.append(numpy.mean(dist))

		elif obj.type == 'solvation':
			atoms, ses, sas = gaudi.score.chem.solvation(ligand_env.atoms())
			ligand_ses = sum(s for (a,s) in zip(atoms, ses) if a in ligand.mol.atoms)
			score.append(ligand_ses)

		elif obj.type == 'rmsd':
			assess = chimera.openModels.open(obj.asess)
			score.append(gaudi.utils.box.rmsd(ligand.mol, assess))
			chimera.openModels.close([assess])
			
	if close:
		chimera.openModels.remove([ligand.mol])
		return score
	if draw and draw_list:
		if 'negvdw' in draw_list:
			gaudi.score.chem.draw_interactions(draw_list['negvdw'], startCol='FF0000', 
				endCol='FF0000', key=3, name="Clashes")
		if 'posvdw' in draw_list: 
			gaudi.score.chem.draw_interactions(draw_list['posvdw'], startCol='00FF00',
				endCol='FFFF00', key=3, name="Hydrophobic interactions")
		if 'hbonds' in draw_list:
			gaudi.score.chem.draw_interactions(draw_list['hbonds'], startCol='00FFFF', 
				endCol='00FFFF', name="H Bonds")
	return ligand

def het_crossover(ind1, ind2):
	for key in ind1:
		if key == 'rotable_bonds':
			ind1[key][:], ind2[key][:] = deap.tools.cxSimulatedBinaryBounded(
				ind1[key], ind2[key], eta=cfg.ga.cx_eta, 
				low=-0.5*cfg.ligand.flexibility, up=0.5*cfg.ligand.flexibility)
		elif key in ('mutamers', 'rotamers'):
			ind1[key], ind2[key] = deap.tools.cxTwoPoint(ind1[key], ind2[key])
		elif key == 'ligand' and len(ind1[key])>2:
			ind1[key], ind2[key] = deap.tools.cxTwoPoint(list(ind1[key]), list(ind2[key]))
			ind1[key], ind2[key] = tuple(ind1[key]), tuple(ind2[key])
		elif key == 'xform':
			xf1 = M.chimera_xform(M.multiply_matrices(*ind1[key]))
			xf2 = M.chimera_xform(M.multiply_matrices(*ind2[key]))
			interp = M.xform_matrix(M.interpolate_xforms(xf1, chimera.Point(0,0,0), 
														xf2, 0.5))
			interp_rot = [ x[:3]+(0,) for x in interp ]
			interp_tl = [ y[:3]+x[-1:] for x, y in zip(interp, M.identity_matrix())]
			ind1[key], ind2[key] =  (ind1[key][0], interp_rot, ind1[key][-1]), \
									(interp_tl, ind2[key][1], ind2[key][-1])

	return ind1, ind2

def het_mutation(ind, indpb):
	for key in ind:
		if key == 'ligand':
			ind[key] = toolbox.ligand()
		elif key == 'rotable_bonds':
			ind[key] = deap.tools.mutPolynomialBounded(ind[key], 
				eta=cfg.ga.mut_eta, low=-0.5*cfg.ligand.flexibility, 
				up=0.5*cfg.ligand.flexibility, indpb=indpb)[0]
		elif key == 'mutamers':
			ind[key] = deap.tools.mutUniformInt(ind[key], 
				low=0, up=len(residues)-1, indpb=indpb)[0]
		elif key == 'rotamers':
			ind[key] = deap.tools.mutUniformInt(ind[key], 
				low=0, up=8, indpb=indpb)[0]
		elif key == 'xform' and random.random() < indpb:
			# Careful! Mutation generates a whole NEW position (similar to eta ~= 0)
			# TODO: We could use a eta param in mutation by interpolating original and 
			# a new random xform with a given `frac` parameter
			ind['xform'] = gaudi.move.rand_xform(origin, cfg.protein.radius)

	return ind,

def similarity(a, b):
	atoms1, atoms2 = ligands[a['ligand']].mol.atoms, ligands[b['ligand']].mol.atoms
	atoms1.sort(key=lambda x: x.serialNumber)
	atoms2.sort(key=lambda x: x.serialNumber)

	try: 
		xf1, xf2 = M.multiply_matrices(*a['xform']), M.multiply_matrices(*b['xform'])
		xf1, xf2 = M.chimera_xform(xf1), M.chimera_xform(xf2)
	except KeyError: #covalent docking does not use xforms!
		xf1, xf2 = chimera.Xform(), chimera.Xform()

	sqdist = sum( xf1.apply(a.coord()).sqdistance(xf2.apply(a.coord())) 
					for a, b in zip(atoms1, atoms2) )
	rmsd = math.sqrt(sqdist / float(len(atoms1)))
	
	return rmsd < 0.25
##/ FUNCTIONS

## Initialize workspace
cfg = gaudi.utils.parse.Settings(sys.argv[1])
weights = cfg.weights() if len(sys.argv)<=2 else map(float, sys.argv[2:])
deap.creator.create("FitnessMax", deap.base.Fitness, weights=weights)
deap.creator.create("Individual", dict, fitness=deap.creator.FitnessMax,
					fitness_names=['{}_{}'.format(*obj) 
								for obj in enumerate(cfg.list_objectives())])

# Open protein
protein, = chimera.openModels.open(cfg.protein.path)

# Set up ligands
ligand_env = chimera.selection.ItemizedSelection()
if not hasattr(cfg.ligand, 'bondto') or not cfg.ligand.bondto:
	origin = box.atoms_by_serial(cfg.protein.origin, atoms=protein.atoms)[0].coord()
	covalent = False
else:
	origin = box.atoms_by_serial(cfg.ligand.bondto, atoms=protein.atoms)[0]
	covalent = True
	
rotations = True if cfg.ligand.flexibility else False
ligands = gaudi.molecule.Library(cfg.ligand.path, origin=origin, covalent=covalent, 
							flexible=rotations)

# Operators and genes
genes = []
toolbox = deap.base.Toolbox()
toolbox.register("ligand", random.choice, ligands.catalog)
genes.append(toolbox.ligand)

if not covalent:
	toolbox.register("xform", gaudi.move.rand_xform, origin, cfg.protein.radius)
	genes.append(toolbox.xform)

if hasattr(cfg.ligand, 'flexibility') and cfg.ligand.flexibility:
	if cfg.ligand.flexibility > 360: 
		cfg.ligand.flexibility = 360.0
	toolbox.register("rand_angle", random.uniform, -0.5*cfg.ligand.flexibility, 
					0.5*cfg.ligand.flexibility)
	toolbox.register("rotable_bonds", deap.tools.initRepeat, list,
						toolbox.rand_angle, n=30)
	genes.append(toolbox.rotable_bonds) 

if hasattr(cfg, 'rotamers'):
	residues = [ r for r in protein.residues if r.id.position in cfg.rotamers.residues ]
	toolbox.register("rand_rotamer", random.randint, 0, cfg.rotamers.top-1)
	toolbox.register("rotamers", deap.tools.initRepeat, list,
						toolbox.rand_rotamer, n=len(cfg.rotamers.residues))
	genes.append(toolbox.rotamers)
	if cfg.rotamers.mutate == "all" or isinstance(cfg.rotamers.mutate, list):
		AA = ['ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLU', 'GLN',
			  'GLY', 'HIS', 'ILE', 'LEU', 'LYS', 'MET', 'PHE',
			  'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL' ]
		if isinstance(cfg.rotamers.mutate, list):
			AA = [ AA[i-1] for i in cfg.rotamers.mutate if i<=20 ]
		toolbox.register("rand_aa", random.randint, 0, len(AA)-1)
		toolbox.register("mutamers", deap.tools.initRepeat, list,
							toolbox.rand_aa, n=len(cfg.rotamers.residues))
		genes.append(toolbox.mutamers)

toolbox.register("toDict", 
	(lambda ind, *fn: ind((f.__name__, f()) for f in fn)))

# Individual and population
toolbox.register("individual", toolbox.toDict, deap.creator.Individual, *genes)
toolbox.register("population", deap.tools.initRepeat, list, toolbox.individual)

# Aliases for algorithm
toolbox.register("evaluate", evaluate)
toolbox.register("mate", het_crossover)
toolbox.register("mutate", het_mutation, indpb=cfg.ga.mut_indpb)
toolbox.register("select", deap.tools.selNSGA2)

def main():
	pop = toolbox.population(n=cfg.ga.pop)
	hof = deap.tools.ParetoFront(similarity) if cfg.ga.pareto \
			else deap.tools.HallOfFame(cfg.default.results, similarity)
	stats = deap.tools.Statistics(lambda ind: ind.fitness.values)
	numpy.set_printoptions(precision=cfg.default.precision)
	stats.register("avg", numpy.mean, axis=0)
	stats.register("min", numpy.min, axis=0)
	stats.register("max", numpy.max, axis=0)
	pop, log = deap.algorithms.eaMuPlusLambda(pop, toolbox, 
		mu = int(cfg.ga.mu*cfg.ga.pop), lambda_= int(cfg.ga.lambda_*cfg.ga.pop), 
		cxpb=cfg.ga.cx_pb, mutpb=cfg.ga.mut_pb, 
		ngen=cfg.ga.gens, stats=stats, halloffame=hof)
	return pop, log, hof

if __name__ == "__main__":	
	print "Scores:", ', '.join(o.type for o in cfg.objectives)
	pop, log, hof = main()

	rank = box.write_individuals(hof, cfg.default.savepath,	
								cfg.default.savename, evaluate)
	out = open(cfg.default.savepath+cfg.default.savename+'.gaudi', 'w+')
	print >> out, '# Generated by GAUDI'
	results = { 'GAUDI.protein': cfg.protein.path,
					'GAUDI.results': rank}
	print >> out, yaml.dump(results, default_flow_style=False)
	out.close()

	#Display best individual
	if not chimera.nogui:
		evaluate(hof[0], close=False, draw=True)