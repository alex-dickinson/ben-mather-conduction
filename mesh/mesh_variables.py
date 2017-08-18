class MeshVariable(object):
    """
    Mesh variables live on the global mesh
    Every time its data is called a local instance is returned
    """
    def __init__(self, name, dm):
        self._dm = dm
        name = str(name)

        # mesh variable vector
        self._gdata = dm.createGlobalVector()
        self._ldata = dm.createLocalVector()

        self._gdata.setName(name)
        self._ldata.setName(name)

        self.size = self._ldata.getSizes()[0]

    def __getitem__(self, pos):
        self._dm.globalToLocal(self._gdata, self._ldata)
        return self._ldata[pos]

    def __setitem__(self, pos, value):
        self._ldata[pos] = value
        self._dm.localToGlobal(self._ldata, self._gdata)


    @property
    def array(self):
        self._dm.globalToLocal(self._gdata, self._ldata)
        return self._ldata


    @property
    def data(self):
        pass

    @data.getter
    def data(self):
        print "getter"
        self._dm.globalToLocal(self._gdata, self._ldata)
        return self._ldata

    @data.setter
    def data(self, val):
        print "setter"
        if type(val) is float:
            self._ldata.set(val)
            self._gdata.set(val)
        else:
            self._ldata.setArray(val)
            self._dm.localToGlobal(self._ldata, self._gdata)

    @data.deleter
    def data(self):
        print "deleter"
        self._ldata.destroy()
        self._gdata.destroy()

    def getGlobal(self):
        print "global"
        return self._gdata

    def getLocal(self):
        print "local"
        return self.data